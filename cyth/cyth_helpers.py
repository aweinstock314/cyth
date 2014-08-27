"""
python -c "import doctest, cyth; print(doctest.testmod(cyth.cyth_helpers))"

TODO: Change this file to cyth_manglers? Functions which mangle names?
"""
from __future__ import absolute_import, division, print_function
from os.path import splitext, split, join, relpath
import utool
import os
import astor

rrr = utool.inject_reload_function(__name__, 'cyth_helpers')


def get_py_module_name(py_fpath):
    relfpath = relpath(py_fpath, os.getcwd())
    name, ext = splitext(relfpath)
    assert ext == '.py', 'bad input'
    modname = name.replace('/', '.').replace('\\', '.')
    return modname


def get_cyth_name(py_name):
    """
    >>> py_name = 'vtool.keypoint'
    >>> cy_name = get_cyth_name(py_name)
    >>> print(cy_name)
    vtool._keypoint_cyth
    """
    # Ensure other modules are not affected
    components = py_name.split('.')
    components[-1] = '_' + components[-1] + '_cyth'
    cy_name = '.'.join(components)
    return cy_name


def get_cyth_path(py_fpath):
    """
    >>> py_fpath = '/foo/vtool/vtool/keypoint.py'
    >>> cy_fpath = get_cyth_path(py_fpath)
    >>> print(cy_fpath)
    /foo/vtool/vtool/_keypoint_cyth.pyx
    """
    dpath, fname = split(py_fpath)
    name, ext = splitext(fname)
    assert ext == '.py', 'not a python file'
    cy_fpath = join(dpath, get_cyth_name(name) + '.pyx')
    return cy_fpath


def get_c_path(cy_fpath):
    """
    >>> cy_fpath = '/foo/vtool/vtool/_linalg_cyth.pyx'
    >>> print(cy_fpath)
    /foo/vtool/vtool/_keypoint_cyth.pyx
    """
    dpath, fname = split(cy_fpath)
    name, ext = splitext(fname)
    assert ext == '.pyx', 'not a cython file'
    c_fpath = join(dpath, name + '.c')
    return c_fpath


def get_cyth_bench_path(py_fpath):
    """
    >>> py_fpath = '/foo/vtool/vtool/keypoint.py'
    >>> cy_fpath = get_cyth_bench_path(py_fpath)
    >>> print(cy_fpath)
    /foo/vtool/vtool/_keypoint_cyth_bench.py
    """
    dpath, fname = split(py_fpath)
    name, ext = splitext(fname)
    assert ext == '.py', 'not a python file'
    cy_fpath = utool.unixpath(join(dpath, get_cyth_name(name) + '_bench.py'))
    return cy_fpath


def get_cyth_pxd_path(py_fpath):
    """
    >>> py_fpath = '/foo/vtool/vtool/keypoint.py'
    >>> cy_fpath = get_cyth_pxd_path(py_fpath)
    >>> print(cy_fpath)
    /foo/vtool/vtool/_keypoint_cyth.pxd
    """
    dpath, fname = split(py_fpath)
    name, ext = splitext(fname)
    assert ext == '.py', 'not a python file'
    cy_fpath = utool.unixpath(join(dpath, get_cyth_name(name) + '.pxd'))
    return cy_fpath


def get_cyth_safe_funcname(pyth_funcname):
    return pyth_funcname + '_cyth'


def ast_to_sourcecode(node):
    generator = astor.codegen.SourceGenerator(' ' * 4)
    generator.visit(node)
    return ''.join(generator.result)
