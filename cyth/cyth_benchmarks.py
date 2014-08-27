"""
#python -c "import cyth, doctest; print(doctest.testmod(cyth.cyth_benchmarks))"
"""
from __future__ import absolute_import, division, print_function
import utool
import doctest
import ast
import astor
from cyth import cyth_helpers


def replace_funcalls(source, funcname, replacement):
    """
    >>> from cyth_script import *  # NOQA
    >>> replace_funcalls('foo(5)', 'foo', 'bar')
    'bar(5)'
    >>> replace_funcalls('foo(5)', 'bar', 'baz')
    'foo(5)'
    """

    # FIXME: !!!
    # http://docs.cython.org/src/userguide/wrapping_CPlusPlus.html#nested-class-declarations
    # C++ allows nested class declaration. Class declarations can also be nested in Cython:
    # Note that the nested class is declared with a cppclass but without a cdef.
    class FunctioncallReplacer(ast.NodeTransformer):
        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == funcname:
                node.func.id = replacement
            return node
    generator = astor.codegen.SourceGenerator(' ' * 4)
    generator.visit(FunctioncallReplacer().visit(ast.parse(source)))
    return ''.join(generator.result)
    #return ast.dump(tree)


def parse_doctest_examples(source):
    # parse list of docstrings
    comment_iter = doctest.DocTestParser().parse(source)
    # remove any non-doctests
    example_list = [c for c in comment_iter if isinstance(c, doctest.Example)]
    return example_list


def get_benchline(src, funcname):
    """ Returns the  from a doctest source """
    pt = ast.parse(src)
    assert isinstance(pt, ast.Module), type(pt)
    body = pt.body
    if len(body) != 1:
        return None
    stmt = body[0]
    if not isinstance(stmt, (ast.Expr, ast.Assign)):
        return None
    if isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Name):
        if stmt.value.func.id == funcname:
            benchline = cyth_helpers.ast_to_sourcecode(stmt.value)
            return benchline


def make_benchmarks(funcname, docstring, py_modname):
    r"""
    >>> from cyth.cyth_script import *  # NOQA
    >>> funcname = 'replace_funcalls'
    >>> docstring = replace_funcalls.func_doc
    >>> py_modname = 'cyth.cyth_script'
    >>> benchmark_list = list(make_benchmarks(funcname, docstring, py_modname))
    >>> print(benchmark_list)
    [[("replace_funcalls('foo(5)', 'foo', 'bar')", "_replace_funcalls_cyth('foo(5)', 'foo', 'bar')"), ("replace_funcalls('foo(5)', 'bar', 'baz')", "_replace_funcalls_cyth('foo(5)', 'bar', 'baz')")], "from cyth.cyth_script import _replace_funcalls_cyth\nfrom cyth_script import *  # NOQA\nreplace_funcalls('foo(5)', 'foo', 'bar')\nreplace_funcalls('foo(5)', 'bar', 'baz')\n"]

    #>>> output = [((x.source, x.want), y.source, y.want) for x, y in benchmark_list]
    #>>> print(utool.hashstr(repr(output)))
    """
    doctest_examples = parse_doctest_examples(docstring)
    test_lines = []
    cyth_lines = []
    setup_lines = []
    cyth_funcname = cyth_helpers.get_cyth_name(funcname)
    for example in doctest_examples:
        benchline = get_benchline(example.source, funcname)
        if benchline is not None:
            test_lines.append(benchline)
            cyth_lines.append(replace_funcalls(benchline, funcname, cyth_funcname))
            setup_lines.append(example.source)
        else:
            setup_lines.append(example.source)
    test_tuples = list(zip(test_lines, cyth_lines))
    setup_script = utool.unindent(''.join(setup_lines))
    #modname = 'vtool.keypoint'
    setup_script = 'from %s import %s\n' % (py_modname, cyth_funcname,) + setup_script
    return test_tuples, setup_script


def parse_benchmarks(funcname, docstring, py_modname):
    test_tuples_, setup_script_ = make_benchmarks(funcname, docstring, py_modname)
    if len(test_tuples_) == 0:
        test_tuples = '[]'
    else:
        test_tuples = '[\n' + (' ' * 8)  + '\n    '.join(list(map(str, test_tuples_))) + '\n    ]'  # NOQA
    setup_script = utool.indent(setup_script_).strip()  # NOQA
    benchmark_name = utool.quasiquote('run_benchmark_{funcname}')
    #test_tuples, setup_script = make_benchmarks('''{funcname}''', '''{docstring}''')
    # http://en.wikipedia.org/wiki/Relative_change_and_difference
    bench_code_fmt_ = r'''
    def {benchmark_name}(iterations):
        test_tuples = {test_tuples}
        setup_script = textwrap.dedent("""
        {setup_script}
        """)
        time_line = lambda line: timeit.timeit(stmt=line, setup=setup_script, number=iterations)
        time_pair = lambda (x, y): (time_line(x), time_line(y))
        def print_timing_info(tup):
            from math import log
            print('\n---------------')
            print('[bench] timing {benchmark_name} for %d iterations' % (iterations))
            print('[bench] tests:')
            print('    ' + str(tup))
            (pyth_time, cyth_time) = time_pair(tup)
            print("[bench.python] {funcname} time=%f seconds" % (pyth_time))
            print("[bench.cython] {funcname} time=%f seconds" % (cyth_time))
            time_delta = cyth_time - pyth_time
            #pcnt_change_wrt_pyth = (time_delta / pyth_time) * 100
            #pcnt_change_wrt_cyth = (time_delta / cyth_time) * 100
            pyth_per_cyth = (pyth_time / cyth_time) * 100
            inv_cyth_per_pyth = 1 / (cyth_time / pyth_time) * 100
            nepers  = log(cyth_time / pyth_time)
            if time_delta < 0:
                print('[bench.result] cython was %.1f%% of the speed of python' % (inv_cyth_per_pyth,))
                #print('[bench.result] cython was %.1fx faster' % (-pcnt_change_wrt_pyth,))
                print('[bench.result] cython was %.1f nepers faster' % (-nepers,))
                print('[bench.result] cython was faster by %f seconds' % -time_delta)
            else:
                print('[bench.result] cython was %.1f%% of the speed of python' % (pyth_per_cyth,))
                #print('[bench.result] cython was %.1fx slower' % (pcnt_change_wrt_pyth,))
                print('[bench.result] cython was %.1f nepers slower' % (nepers,))
                print('[bench.result] python was faster by %f seconds' % time_delta)
            pyth_call, cyth_call = tup
            run_doctest(pyth_call, cyth_call, setup_script)
            return (pyth_time, cyth_time)
        return list(map(print_timing_info, test_tuples))'''
    bench_code_fmt = utool.unindent(bench_code_fmt_).strip('\n')
    bench_code = utool.quasiquote(bench_code_fmt)
    return (benchmark_name, bench_code)
