"""
python -c "import cyth, doctest; print(doctest.testmod(cyth.cyth_macros))"
"""
from __future__ import absolute_import, division, print_function
import parse
import re
from functools import partial
from .cyth_decorators import macro


def parens(str_):
    return '(' + str_ + ')'


def is_constant(expr, known_constants=[]):
    if re.match(r'\d+', expr) or expr in known_constants:
        return True
    return False


def get_slicerange(slice_, dim_name='dim0'):
    """
    slice_ = 'start:stop:stride'
    """
    tup = slice_.split(':')
    if len(tup) == 0:
        raise AssertionError('')
    if len(tup) == 1:
        if is_constant(tup[0]):
            slicerange = ('1',)
        else:
            raise NotImplementedError('custom input')
    elif len(tup) == 2:
        start = '0' if tup[0] == '' else tup[0]
        stop = dim_name if tup[1] == '' else tup[1]
        slicerange = (start, stop)
    elif len(tup) == 3:
        start = '0' if tup[0] == '' else tup[0]
        stop = dim_name if tup[1] == '' else tup[1]
        stride = '1' if tup[2] == '' else tup[2]
        slicerange = (start, stop, stride)
    else:
        raise AssertionError('??')
    return slicerange


def make_gensym_function(suffix='gensym'):
    gensym_dict = {}
    def gensym(prefix):
        number = gensym_dict.get(prefix, 0)
        gensym_dict[prefix] = number + 1
        return '%s__%s%s' % (prefix, suffix, number)
    return gensym


@macro
def numpy_fancy_index_macro(gensym, lines):
    return map(partial(numpy_fancy_index_assign, gensym), lines)


def numpy_fancy_index_assign(gensym, line):
    """
    Input is gaurenteed to be one numpy array assigning to another.
    Still in development. May break for complicated cases.

    >>> from cyth.cyth_macros import *
    >>> gensym = make_gensym_function()
    >>> line = '_iv21s = invVR_mats[:, 1, :, 2:42, ::-1, , 3:, :]'
    >>> line = '_iv21s = invVR_mats[:, 1, :]'
    >>> block1 = numpy_fancy_index_assign(gensym, '_iv11s = invVR_mats[:, 0, 0]')
    >>> block2 = numpy_fancy_index_assign(gensym, '_iv12s = invVR_mats[:, :, 1]')
    >>> block3 = numpy_fancy_index_assign(gensym, '_iv21s = invVR_mats[:, 1, :]')
    >>> block4 = numpy_fancy_index_assign(gensym, '_iv22s = invVR_mats[:, 1, 1]')
    >>> print('\n'.join((block1, block2, block3, block4)))

    A shape is a tuple of array dimensions

    """
    # Split at assignment
    LHS, RHS = line.split('=')
    # Parse out the fancy index slice
    _parseresult = parse.parse('{arr2}[{fancy_slice}]', RHS.strip())
    _fancy_slice   = _parseresult.named['fancy_slice']

    arr1 = LHS.strip()
    arr2 = _parseresult.named['arr2']
    # Break fancy slices into individual slices
    slice_list = [_.strip() for _ in _fancy_slice.split(',')]

    dim_ix_idx_fmt     = gensym('dim{ix}_idx')
    dim_ix_fmt       = gensym('dim{ix}')
    defdim_fmt       = 'cdef size_t {dim_ix_fmt} = {{arr2}}.shape[{{ix}}]'.format(dim_ix_fmt=dim_ix_fmt)
    #alloc_ouput_fmt  = 'cdef np.ndarray {arr1} = np.ndarray(({LHS_shape}), {arr2}.dtype)'
    alloc_ouput_fmt  = '{arr1} = np.ndarray(({LHS_shape}), {arr2}.dtype)'
    alloc_ouput_fmt  = '{arr1} = np.ndarray(({LHS_shape}), {arr2}.dtype)'
    for_fmt          = '{indent}for {dim_x} in range({dimsize}):'
    assign_index_fmt = '{indent}{arr1}[{LHS_index}] = {arr2}[{RHS_index}]'

    RHS_slicerange_list = [get_slicerange(slice_, dim_ix_fmt.format(ix=ix)) for ix, slice_ in enumerate(slice_list)]
    LHS_slicerange_list = [slicerange for slicerange in RHS_slicerange_list if
                           slicerange[0] != '1']

    LHS_dimsize_list = [slicerange[0]
                        if len(slicerange) == 1 else
                        slicerange[1] + ' - ' + slicerange[0]
                        for slicerange in LHS_slicerange_list]
    RHS_dimsize_list = [slicerange[0]
                         if len(slicerange) == 1 else
                         slicerange[1] + ' - ' + slicerange[0]
                         for slicerange in RHS_slicerange_list ]

    #LHS_shape_list = [', '.join(slicerange) for slicerange in LHS_slicerange_list]

    LHS_shape = parens(', '.join(LHS_dimsize_list))
    #RHS_shape = parens(', '.join(RHS_dimsize_list))

    indent = ''
    for_list = []
    # indexes into the array shapes
    LHS_shapex_list = []
    RHS_shapex_list = []
    # So hacky and special cased
    for ix, dimsize in enumerate(RHS_dimsize_list):
        rhs_slicerange = RHS_slicerange_list[ix]
        dim_x = dim_ix_idx_fmt.format(ix=ix)
        if len(rhs_slicerange) == 1:
            RHS_shapex_list.append(dimsize)
            #LHS_shapex_list.append('0')
        else:
            LHS_shapex_list.append(dim_x)
            RHS_shapex_list.append(dim_x)
            for_list.append(for_fmt.format(indent=indent, dim_x=dim_x,
                                           dimsize=dimsize))
            indent += '    '

    RHS_defdim_list = [defdim_fmt.format(ix=ix, arr2=arr2) for ix in range(len(slice_list))]

    # Make index expression
    LHS_index = ', '.join(LHS_shapex_list)
    RHS_index = ', '.join(RHS_shapex_list)

    alloc_output_line = alloc_ouput_fmt.format(
        arr1=arr1, arr2=arr2, LHS_shape=LHS_shape)
    defdim_assign = '\n'.join(RHS_defdim_list)

    for_lines = '\n'.join(for_list)

    assign_index_line = assign_index_fmt.format(
        indent=indent, arr1=arr1, LHS_index=LHS_index, arr2=arr2, RHS_index=RHS_index)

    output_lines = [defdim_assign, alloc_output_line, for_lines, assign_index_line]
    output_block = '\n' + '\n'.join(output_lines) + '\n\n'
    print(output_block)
    return output_block


def numpy_fancy_index_assign1(gensym, line):
    """
    Input is gaurenteed to be one numpy array assigning to another.
    Still in development. May break for complicated cases.

    >>> from cyth.cyth_macros import *
    >>> gensym = make_gensym_function()
    >>> line = '_iv21s = invVR_mats[:, 1, :]'
    >>> block1 = numpy_fancy_index_assign(gensym, '_iv11s = invVR_mats[:, 0, 0]')
    >>> block2 = numpy_fancy_index_assign(gensym, '_iv12s = invVR_mats[:, :, 1]')
    >>> block3 = numpy_fancy_index_assign(gensym, '_iv21s = invVR_mats[:, 1, :]')
    >>> block4 = numpy_fancy_index_assign(gensym, '_iv22s = invVR_mats[:, 1, 1]')
    >>> print('\n'.join((block1, block2, block3, block4)))

    A shape is a tuple of array dimensions

    """
    # Split at assignment
    LHS, RHS = line.split('=')
    # Parse out the fancy index slice
    _parseresult = parse.parse('{arr2}[{fancy_slice}]', RHS.strip())
    _fancy_slice   = _parseresult.named['fancy_slice']

    arr1 = LHS.strip()
    arr2 = _parseresult.named['arr2']
    # Break fancy slices into individual slices
    slice_list = [_.strip() for _ in _fancy_slice.split(',')]

    dim_ix_idx_fmt     = gensym('dim{ix}_idx')
    dim_ix_fmt       = gensym('dim{ix}')
    defdim_fmt       = 'cdef Py_ssize_t {dim_ix_fmt} = {{arr2}}.shape[{{ix}}]'.format(dim_ix_fmt=dim_ix_fmt)
    #alloc_ouput_fmt  = 'cdef np.ndarray {arr1} = np.ndarray(({LHS_shape}), {arr2}.dtype)'
    alloc_ouput_fmt  = '{arr1} = np.empty(({LHS_shape}))'
    #, {arr2}.dtype
    for_fmt          = '{indent}for {dim_x} in range({dimsize}):'
    assign_index_fmt = '{indent}{arr1}[{LHS_index}] = {arr2}[{RHS_index}]'

    RHS_slicerange_list = [get_slicerange(slice_, dim_ix_fmt.format(ix=ix))
                           for ix, slice_ in enumerate(slice_list)]
    LHS_slicerange_list = [slicerange for slicerange in RHS_slicerange_list if
                           slicerange[0] != '1']

    LHS_dimsize_list = [slicerange[0]
                        if len(slicerange) == 1 else
                        slicerange[1] + ' - ' + slicerange[0]
                        for slicerange in LHS_slicerange_list]
    RHS_dimsize_list = [slicerange[0]
                         if len(slicerange) == 1 else
                         slicerange[1] + ' - ' + slicerange[0]
                         for slicerange in RHS_slicerange_list ]

    #LHS_shape_list = [', '.join(slicerange) for slicerange in LHS_slicerange_list]

    LHS_shape = parens(', '.join(LHS_dimsize_list))
    #RHS_shape = parens(', '.join(RHS_dimsize_list))

    indent = ''
    for_list = []
    # indexes into the array shapes
    LHS_shapex_list = []
    RHS_shapex_list = []
    # So hacky and special cased
    for ix, dimsize in enumerate(RHS_dimsize_list):
        rhs_slicerange = RHS_slicerange_list[ix]
        dim_x = dim_ix_idx_fmt.format(ix=ix)
        if len(rhs_slicerange) == 1:
            RHS_shapex_list.append(dimsize)
            #LHS_shapex_list.append('0')
        else:
            LHS_shapex_list.append(dim_x)
            RHS_shapex_list.append(dim_x)
            for_list.append(for_fmt.format(indent=indent, dim_x=dim_x,
                                           dimsize=dimsize))
            indent += '    '

    RHS_defdim_list = [defdim_fmt.format(ix=ix, arr2=arr2) for ix in range(len(slice_list))]

    # Make index expression
    LHS_index = ', '.join(LHS_shapex_list)
    RHS_index = ', '.join(RHS_shapex_list)

    alloc_output_line = alloc_ouput_fmt.format(
        arr1=arr1, arr2=arr2, LHS_shape=LHS_shape)
    defdim_assign = '\n'.join(RHS_defdim_list)

    for_lines = '\n'.join(for_list)

    assign_index_line = assign_index_fmt.format(
        indent=indent, arr1=arr1, LHS_index=LHS_index, arr2=arr2, RHS_index=RHS_index)

    output_lines = [defdim_assign, alloc_output_line, for_lines, assign_index_line]
    output_block = '\n' + '\n'.join(output_lines) + '\n\n'
    print(output_block)
    return output_block
