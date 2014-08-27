#!/usr/bin/env python2
"""
#python -c "import cyth, doctest; print(doctest.testmod(cyth.cyth_script))"
python -m doctest cyth_script.py
ut
python cyth/cyth_script.py ~/code/fpath
cyth_script.py ~/code/ibeis/ibeis/model/hots
cyth_script.py "~/code/vtool/vtool"

"""
from __future__ import absolute_import, division, print_function
from six.moves import map
import utool
import sys
import os
from os.path import isfile
from cyth import cyth_helpers
from cyth import cyth_parser
from cyth import cyth_benchmarks
import ast
import astor
BASE_CLASS = astor.codegen.SourceGenerator


# See astor/codegen.py for details
# https://github.com/berkerpeksag/astor/blob/master/astor/codegen.py
CYTHON_HTML = '--annotate' in sys.argv or '-a' in sys.argv
CYTHON_MAKE_C = '--makec' in sys.argv
CYTHON_BUILD = '--build' in sys.argv


def translate_fpath(py_fpath):
    """ creates a cython pyx file from a python file with cyth tags
    >>> from cyth.cyth_script import *  # NOQA
    >>> py_fpath = utool.unixpath('~/code/vtool/vtool/linalg.py')
    """
    # If -a is given, generate cython html for each pyx file
    # Get cython pyx and benchmark output path
    cy_pyxpath = cyth_helpers.get_cyth_path(py_fpath)
    cy_pxdpath = cyth_helpers.get_cyth_pxd_path(py_fpath)
    cy_benchpath = cyth_helpers.get_cyth_bench_path(py_fpath)
    # Infer the python module name
    py_modname = cyth_helpers.get_py_module_name(py_fpath)
    # Read the python file
    py_text = utool.read_from(py_fpath, verbose=False)
    # dont parse files without tags
    if py_text.find('CYTH') == -1:
        return None
    print('\n___________________')
    print('[cyth.translate_fpath] py_fpath=%r' % py_fpath)
    # Parse the python file
    visitor = cyth_parser.CythVisitor(py_modname=py_modname)
    visitor.visit(ast.parse(py_text))
    # Get the generated pyx file and benchmark file
    pyx_text, pxd_text = visitor.get_result()
    bench_text = visitor.get_benchmarks()
    # Write pyx and benchmark
    utool.write_to(cy_pyxpath, pyx_text)
    utool.write_to(cy_pxdpath, pxd_text, verbose=False)
    utool.write_to(cy_benchpath, bench_text, verbose=False)
    if CYTHON_HTML:
        print('[cyth.translate_fpath] generating annotation html')
        cython_exe = utool.get_cython_exe()
        os.system(cython_exe + ' -a ' + cy_pyxpath)
    if CYTHON_MAKE_C:
        print('[cyth.translate_fpath] generating cython c')
        cython_exe = utool.get_cython_exe()
        os.system(cython_exe + ' ' + cy_pyxpath)
    if CYTHON_BUILD:
        gcc_exe = 'gcc'
        print('[cyth.translate_fpath] generating c library')
        c_path = cyth_helpers.get_c_path(cy_pyxpath)
        #C:\MinGW\bin\gcc.exe -w -Wall -m32 -lpython27 -IC:\Python27\Lib\site-packages\numpy\core\include -IC:\Python27\include -IC:\Python27\PC -IC:\Python27\Lib\site-packages\numpy\core\include -LC:\Python27\libs -o _linalg_cyth.pyd -c _linalg_cyth.c
        os.system(gcc_exe + ' ' + c_path)
    return cy_benchpath


def translate(*paths):
    """ Translates a list of paths """

    cy_bench_list = []
    for fpath in paths:
        if isfile(fpath):
            abspath = utool.unixpath(fpath)
            cy_bench = translate_fpath(abspath)
            if cy_bench is not None:
                cy_bench_list.append(cy_bench)

    if len(cy_bench_list) > 0:
        runbench_shtext = cyth_benchmarks.build_runbench_shell_text(cy_bench_list)
        runbench_pytext = cyth_benchmarks.build_runbench_pyth_text(cy_bench_list)

        utool.write_to('run_cyth_benchmarks.sh', runbench_shtext)
        utool.write_to('run_cyth_benchmarks.py', runbench_pytext)
        #try:
        os.chmod('run_cyth_benchmarks.sh', 33277)
        os.chmod('run_cyth_benchmarks.py', 33277)
        #except OSError:
        #    pass


def translate_all():
    """ Translates a all python paths in directory """
    dpaths = utool.ls_moduledirs('.')
    #print('[cyth] translate_all: %r' % (dpaths,))

    globkw = {
        'recursive': True,
        'with_dirs': False,
        'with_files': True
    }
    # Find all unique python files in directory
    fpaths_iter = [utool.glob(utool.unixpath(dpath), '*.py', **globkw)
                   for dpath in dpaths]
    fpath_iter = utool.iflatten(fpaths_iter)
    abspath_iter = map(utool.unixpath, fpath_iter)
    fpath_list = list(set(list(abspath_iter)))
    #print('[cyth] translate_all: %s' % ('\n'.join(fpath_list),))
    # Try to translate each
    translate(*fpath_list)
    #for fpath in fpath_list:
    #    abspath = utool.unixpath(fpath)
    #    translate_fpath(abspath)


#exec(cyth.import_cyth_execstr(__name__))

if __name__ == '__main__':
    print('[cyth] main')
    input_path_list = utool.get_fpath_args(sys.argv[1:], pat='*.py')
    print(input_path_list)
    print('[cyth] nInput=%d' % (len(input_path_list,)))
    translate(*input_path_list)
