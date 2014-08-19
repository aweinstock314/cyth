"""
python -c "import cyth, doctest; print(doctest.testmod(cyth.cyth_pragmas))"
"""
from __future__ import absolute_import, division, print_function
import parse
import re


def parens(str_):
    return '(' + str_ + ')'


def is_constant(expr, known_constants=[]):
    if re.match(r'\d+', expr) or expr in known_constants:
        return True
    return False


def get_slicerange(slice_, ix=0):
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
        stop = 'shape_{ix}'.format(ix=ix) if tup[1] == '' else tup[1]
        slicerange = (start, stop)
    elif len(tup) == 3:
        start = '0' if tup[0] == '' else tup[0]
        stop = 'shape_{ix}'.format(ix=ix) if tup[1] == '' else tup[1]
        stride = '1' if tup[2] == '' else tup[2]
        slicerange = (start, stop, stride)
    else:
        raise AssertionError('??')
    return slicerange


def numpy_fancy_index_assign(line):
    """
    Input is gaurenteed to be one numpy array assigning to another.
    Still in development. May break for complicated cases.

    >>> from cyth.cyth_pragmas import *
    >>> line = '_iv21s = invVR_mats[:, 1, :]'
    >>> block1 = numpy_fancy_index_assign('_iv11s = invVR_mats[:, 0, 0]')
    >>> block2 = numpy_fancy_index_assign('_iv12s = invVR_mats[:, :, 1]')
    >>> block3 = numpy_fancy_index_assign('_iv21s = invVR_mats[:, 1, :]')
    >>> print('\n'.join((block1, block2, block3, block4)))

    A shape is a tuple of array dimensions

    """
    # Split at assignment
    rhs, lhs = line.split('=')
    # Parse out the fancy index slice
    _parseresult = parse.parse('{arr2}[{fancy_slice}]', lhs.strip())
    _fancy_slice   = _parseresult.named['fancy_slice']

    arr1 = rhs.strip()
    arr2 = _parseresult.named['arr2']
    # Break fancy slices into individual slices
    slice_list = [_.strip() for _ in _fancy_slice.split(',')]

    dim_x_fmt        = 'dim{ix}_x'
    defdim_fmt       = 'cdef size_t dim{ix} = {arr2}.shape[{ix}]'
    alloc_ouput_fmt  = 'cdef np.ndarray {arr1} = np.ndarray(({rhs_shape}), {arr2}.dtype)'
    for_fmt          = '{indent}for {dim_x} in range({dimsize}) :'
    assign_index_fmt = '{indent}{arr1}[{rhs_index}] = {arr2}[{lhs_index}]'

    rhs_slicerange_list = [get_slicerange(slice_, ix) for ix, slice_ in enumerate(slice_list)]
    lhs_slicerange_list = [('0',) if len(slicerange) == 1 else slicerange for slicerange in rhs_slicerange_list]

    rhs_dimsize_list = [slicerange[0]
                        if len(slicerange) == 1 else
                        slicerange[1] + ' - ' + slicerange[0]
                        for slicerange in rhs_slicerange_list]
    lhs_dimindex_list = [slicerange[0]
                         if len(slicerange) == 1 else
                         slicerange[1] + ' - ' + slicerange[0]
                         for slicerange in lhs_slicerange_list ]

    rhs_shape_list = [', '.join(slicerange) for slicerange in rhs_slicerange_list]

    #rhs_shape = parens(', '.join(rhs_dimsize_list))
    #lhs_shape = parens(', '.join(lhs_dimsize_list))

    indent = ''
    for_list = []
    # indexes into the array shapes
    rhs_shapex_list = []
    lhs_shapex_list = []
    # So hacky and special cased
    for ix, dimsize in enumerate(rhs_dimsize_list):
        slicerange = rhs_slicerange_list[ix]
        dim_x = dim_x_fmt.format(ix=ix)
        if len(slicerange) == 1:
            lhs_shapex_list.append(dimsize)
            rhs_shapex_list.append('0')
        else:
            rhs_shapex_list.append(dim_x)
            lhs_shapex_list.append(dim_x)
            for_list.append(for_fmt.format(indent=indent, dim_x=dim_x,
                                           dimsize=dimsize))
            indent += '    '

    lhs_defdim_list = [defdim_fmt.format(ix=ix, arr2=arr2) for ix in range(len(slice_list))]

    # Make index expression
    rhs_index = ', '.join(rhs_shapex_list)
    lhs_index = ', '.join(lhs_shapex_list)

    alloc_output_line = alloc_ouput_fmt.format(**locals())
    defdim_assign = '\n'.join(lhs_defdim_list)

    for_lines = '\n'.join(for_list)
    assign_index_line = assign_index_fmt.format(**locals())

    output_lines = [defdim_assign, alloc_output_line, for_lines, assign_index_line]
    output_block = '\n'.join(output_lines)
    print(output_block)
    return output_block
