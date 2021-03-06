"""
#python -c "import cyth, doctest; print(doctest.testmod(cyth.cyth_parser))"
"""
from __future__ import absolute_import, division, print_function
import six
from six.moves import zip, map, filter
from itertools import chain
import utool
import sys
from cyth import cyth_helpers
import ast
#import codegen  # NOQA
import astor
import re
import cyth  # NOQA
from copy import deepcopy
from cyth.cyth_decorators import MACRO_EXPANDERS_DICT
from cyth import cyth_benchmarks
import cyth.cyth_macros
BASE_CLASS = astor.codegen.SourceGenerator


class CythVisitor(BASE_CLASS):
    indent_level = 0
    emit = sys.stdout.write

    def __init__(self, indent_with=' ' * 4, add_line_information=False,
                 py_modname=None):
        super(CythVisitor, self).__init__(indent_with, add_line_information)
        self.benchmark_names = []
        self.benchmark_codes = []
        self.py_modname = py_modname
        #print('in module ', py_modname)
        self.imported_modules = {}
        self.imported_functions = {}
        #self.all_funcalls = []
        #self.imports_with_usemaps = {}
        self.import_lines = ['cimport cython', 'import cython']
        self.cimport_whitelist = ['numpy']
        self.cimport_blacklist = ['numpy.core.umath_tests']
        self.import_from_blacklist = ['range', 'map', 'zip']
        self.cythonized_funcs = {}
        self.plain_funcs = {}
        self.fpig = FirstpassInformationGatherer()
        self.spig = SecondpassInformationGatherer(self.fpig)
        self.modules_to_cimport = []
        self.interface_lines = []  # generated for the pxd header
        self.gensym = cyth.cyth_macros.make_gensym_function()

    def get_result(self):
        """
        returns cythonized pyx text resulting from parsing the py file with cyth
        markups
        """
        cyth_text = (
            '\n'.join(self.import_lines) +
            '\n' +
            ''.join(self.result)
        )
        pxd_text = ('cimport numpy as np\n' + '\n\n'.join(self.interface_lines))
        return cyth_text, pxd_text

    def process_args(self, args, vararg, kwarg, defaults=None):
        processed_argslist = map(self.visit, args)
        if vararg:
            processed_argslist.append('*%s' % vararg)
        if kwarg:
            processed_argslist.append('**%s' % kwarg)
        if defaults is not None:
            first_non_default = len(args) - len(defaults)
            for (ix, de) in enumerate(defaults):
                processed_argslist[first_non_default + ix] += '=%s' % self.visit(defaults[ix])
        return processed_argslist

    def signature(self, node, typedict={}):
        # remove type declarations that are 'used up' in the function's
        # call signature, to avoid duplicating them in the body
        nonsig_typedict = typedict.copy()
        want_comma = []

        def write_comma():
            if want_comma:
                self.write(', ')
            else:
                want_comma.append(True)

        def loop_args(args, defaults):
            padding = [None] * (len(args) - len(defaults))
            for arg, default in zip(args, padding + defaults):
                if arg.id in typedict:
                    arg_ = typedict[arg.id] + ' ' + arg.id
                    nonsig_typedict.pop(arg.id)
                else:
                    arg_ = arg
                self.write(write_comma, arg_)
                self.conditional_write('=', default)

        loop_args(node.args, node.defaults)
        self.conditional_write(write_comma, '*', node.vararg)
        self.conditional_write(write_comma, '**', node.kwarg)

        kwonlyargs = getattr(node, 'kwonlyargs', None)
        if kwonlyargs:
            if node.vararg is None:
                self.write(write_comma, '*')
            loop_args(kwonlyargs, node.kw_defaults)
        return nonsig_typedict

    def parse_cythdef(self, cyth_def):
        """ Hacky string manipulation parsing """
        #ast.literal_eval(utool.unindent(cyth_def))
        typedict = {}
        cdef_mode = False
        current_indent = 0
        for line_ in cyth_def.splitlines():
            indent_level = utool.get_indentation(line_)
            # Check indentation
            if indent_level > current_indent:
                current_indent = indent_level
            elif indent_level > current_indent:
                current_indent = indent_level
                cdef_mode = False
            line = line_.strip()
            if line.startswith('#'):
                continue
            if len(line) == 0:
                continue
            # parse cdef
            if line.startswith('cdef:'):
                cdef_mode = True
                continue
            if cdef_mode or line.startswith('cdef '):
                def parse_cdef_line(line):
                    """
                    line = 'np.array[float, ndims=2] x, y, z'
                    # todo put in better line parsing
                    # allow for cdef
                    type_ = []
                    lbrackets = 0
                    for sub in line.split(','):
                        sub
                    pass
                    """
                assign_str = line.replace('cdef ', '')
                pos = assign_str.rfind(' ')
                type_ = assign_str[:pos]
                varstr = assign_str[(pos + 1):]
                typedict[varstr] = type_
        return typedict

    def typedict_to_cythdef(self, typedict):
        res = ['cdef:']
        for (id_, type_) in six.iteritems(typedict):
            #print("%s, %s" % (repr(id_), repr(type_)))
            res.append(self.indent_with + type_ + ' ' + id_)
        if len(typedict) == 0:
            res.append(self.indent_with + 'pass')
        return res

    def register_benchmark(self, funcname, docstr, modname):
        if funcname:
            # Parse doctests for benchmarks
            (bench_name, bench_code) = cyth_benchmarks.parse_benchmarks(funcname, docstr, modname)
            self.benchmark_names.append(bench_name)
            self.benchmark_codes.append(bench_code)

    def parse_cyth_markup(self, docstr, toplevel=False, funcdef_node=None):
        """
        Args:
            docstr (str): block of text possibly with cyth markups
            toplevel (bool): True if docstr is in the global scope
            funcdef_node: parent funcdef node for return type inference
        """
        funcname = None if funcdef_node is None else funcdef_node.name
        comment_str = docstr.strip()
        has_markup = comment_str.find('<CYTH') != -1
        # type returned_action = [`defines of string * (string, string) Hashtbl.t | `replace of string] option
        def make_defines(cyth_def, return_type=None):
            typedict = self.parse_cythdef(cyth_def)
            if not return_type:
                return_type = infer_return_type(funcdef_node, typedict)
            actiontup = ('defines', cyth_def, typedict, return_type)
            return actiontup
        # TODO: these actions are old-style cyth commands. Replace them.
        tags_to_actions = [
            ('<CYTH>', lambda cyth_def: make_defines(cyth_def.group(1))),
            ('<CYTH returns="(.*?)">', lambda cyth_def: make_defines(cyth_def.group(2), cyth_def.group(1))),
            ('<CYTH:REPLACE>', lambda cyth_def: ('replace', utool.unindent(cyth_def.group(1)))),
        ]
        end_tag = '</CYTH>'
        regex_flags = re.DOTALL | re.MULTILINE
        regex_to_actions = [(re.compile(tag + '(.*?)' + end_tag, regex_flags), act)
                            for tag, act in tags_to_actions]

        if has_markup:
            # if CYTH markup was found...
            self.register_benchmark(funcname, docstr, self.py_modname)
            if toplevel:
                # hack global cyth-docstrs to always CYTH:REPLACE
                comment_str = re.sub('<CYTH>', '<CYTH:REPLACE>', comment_str)
            for (regex, action) in regex_to_actions:
                match = regex.search(comment_str)
                if match:
                    #cyth_def = match.group(1)
                    actiontup = action(match)
                    return actiontup
            print(comment_str)
            utool.printex(NotImplementedError('no known cyth tag in docstring'),
                           iswarning=True,
                           key_list=['funcname', 'toplevel', 'regex', 'action',
                                     'match', 'comment_str'])
        else:
            # Do nothing if cyth markup was not found
            pass
        return None

    def parse_cyth_preproc_markup(self, docstr, cyth_mode, collect_macro_input,
                                  macro_input_buffer_ptr,
                                  suspended_macro_context_ptr, inline_flag_ptr):
        source_lines = []
        param_typedict = {}
        bodyvars_typedict = {}
        preproc_vars_dict = {'CYTH': True}
        return_type_ptr = [None]
        cyth_mode_ptr = [cyth_mode]
        collect_macro_input_ptr = [collect_macro_input]

        def handle_if(matcher):
            varname = matcher.group(1)
            # change to a stack in order to support nested ifs
            #print('handle_if: %r' % varname)
            cyth_mode_ptr[0] = preproc_vars_dict.get(varname, False)

        def handle_else(matcher):
            #print('handle_else: %r' % (cyth_mode_ptr[0],))
            #cyth_mode_ptr[0] = not cyth_mode_ptr[0]
            pass  # deliberate no-op

        def handle_endif(matcher):
            #print('handle_endif')
            cyth_mode_ptr[0] = False  # pop the top item in the stack for nested ifs

        def handle_returns_decl(matcher):
            return_type_ptr[0] = matcher.group(1)
            #print('handle_returns %r' % return_type_ptr[0])

        def handle_inline(matcher):
            inline_flag_ptr[0] = True

        def handle_macro(matcher):
            """ this should eventually be changed to reuse
                the machinery for multiline """
            macro_name = matcher.group(1)
            suspended_macro_context_ptr[0] = (macro_name,)
            collect_macro_input_ptr[0] = True
            assert len(macro_input_buffer_ptr[0]) == 0, macro_input_buffer_ptr[0]

        def handle_endmacro(matcher):
            """ this is quite a bit hacky, but this is the
                most straightforward way to implement them until the
                parse_cyth_preproc_markup/visit_FunctionDef 'coroutine'
                blob is refactored """
            (macro_name,) = suspended_macro_context_ptr[0]
            lines = macro_input_buffer_ptr[0]
            #print('macro invokation of "%s" on lines %r' % (macro_name, lines))
            expander = MACRO_EXPANDERS_DICT.get(macro_name, None)
            if expander:
                expanded_lines = ['\n'] + expander(self.gensym, lines) + ['\n']
            else:
                errmsg = 'No macro named %r has been registered via the cyth.macro decorator'
                raise NotImplementedError(errmsg % macro_name)

            indented_expanded_lines = [utool.indent(x, indent=self.indent_with * (self.indentation + 1))
                                        for x in expanded_lines]
            #print('output is %r' % expanded_lines)
            source_lines.extend(indented_expanded_lines)
            collect_macro_input_ptr[0] = False
            macro_input_buffer_ptr[0] = []

        oneline_directives = [('#' + a, b) for (a, b) in [
            ('if (.*)', handle_if),
            ('else', handle_else),
            ('endif', handle_endif),
            ('CYTH_RETURNS (.*)', handle_returns_decl),
            ('CYTH_INLINE', handle_inline),
            ('macro ([^ ]*).*', handle_macro),
            ('endmacro', handle_endmacro),  # HACK
        ]]

        def handle_param_types(matcher, lines):
            # the indent/unindent pair is not a no-op: unindent goes all the way,
            # indent just does one step
            #print(lines)
            #cythdef = '\n'.join(['cdef:\n'].append(utool.indent(utool.unindent('\n'.join(lines))).split('\n')))
            #print('synthesized_cythdef = %r' % (cythdef,))
            #param_typedict.update(self.parse_cythdef(cythdef))
            for line in lines:
                tmp_typedict = parse_cdef_line(line)
                #print('%r -> %r' % (line, tmp_typedict))
                param_typedict.update(tmp_typedict)

        def handle_cdef(matcher, lines):
            for line in lines:
                tmp_typedict = parse_cdef_line(line)
                #print('%r -> %r' % (line, tmp_typedict))
                bodyvars_typedict.update(tmp_typedict)

        multiline_directives = [((a + ":"), b) for (a, b) in [
            ('#CYTH_PARAM_TYPES', handle_param_types),
            ('cdef', handle_cdef),
        ]]

        regex_compile_car = lambda (a, b): (re.compile(a), b)
        #print(list(oneline_directives))
        compiled_oneline_directives = list(map(regex_compile_car, oneline_directives))
        compiled_multiline_directives = list(map(regex_compile_car, multiline_directives))

        # hack for lack of labeled continues
        def loop_body(line):
            #print('cyth_mode_ptr[0] = %r, Line "%s"' % (cyth_mode_ptr[0], line))
            for (regex, handler) in compiled_oneline_directives:
                match = regex.search(line)
                if match:
                    handler(match)
                    return None
            for (regex, handler) in compiled_multiline_directives:
                match = regex.search(line)
                if match:
                    return (match, handler)
            if cyth_mode_ptr[0]:
                #if line.strip().startswith('cdef'):
                #    bodyvars_typedict.update(parse_cdef_line(line))
                #    #source_lines.append('\n' + line.replace('cdef [^ ]*', ''))
                ##else:
                source_lines.append('\n' + line)
                return None

        multiline_buffer = []
        multiline_start_indent = None
        do_multiline = None
        for line in docstr.split('\n'):
            #print('do_multiline = %r, Line "%s"' % (do_multiline, line))
            if do_multiline:
                current_indentation = utool.get_indentation(line)
                if multiline_start_indent < current_indentation:
                    multiline_buffer.append(line)
                    continue
                else:
                    #print('calling handler')
                    (match, handler) = do_multiline
                    handler(match, multiline_buffer)
                    multiline_buffer = []
                    multiline_start_indent = None
            do_multiline = loop_body(line)
            if do_multiline:
                assert multiline_buffer == [], multiline_buffer
                multiline_start_indent = utool.get_indentation(line)

        #print('at return, cyth_mode_ptr[0] is %r' % (cyth_mode_ptr[0],))
        return source_lines, cyth_mode_ptr[0], collect_macro_input_ptr[0], param_typedict, bodyvars_typedict, return_type_ptr[0]

    def visit_Module(self, node):
        # cr = CallRecorder()
        # cr.visit(node)
        # self.all_funcalls = cr.calls
        self.fpig.visit(node)
        self.spig.visit(node)

        def get_alias_name(al):
            alias_name = al.name if al.asname is None else al.asname
            return alias_name

        for subnode in node.body:
            # parse for cythtags
            if is_docstring(subnode):
                #print('Encountered global docstring: %s' % repr(subnode.value.s))
                docstr = subnode.value.s
                #actiontup = self.parse_cyth_markup(docstr, toplevel=True)
                #if actiontup is not None:
                #    if actiontup[0] == 'replace':
                #        cyth_def = actiontup[1]
                #        self.newline(extra=1)
                #        self.write(cyth_def)
                hacky_blob_of_retvals = self.parse_cyth_preproc_markup(docstr, False, False, [[]], [None], [False])
                lines = hacky_blob_of_retvals[0]
                self.newline(extra=1)
                for line in lines:
                    self.write(line)
            # try to parse functions for cyth tags
            elif isinstance(subnode, ast.FunctionDef):
                self.visit(subnode)
            # register imports
            elif isinstance(subnode, ast.Import):
                for alias in subnode.names:
                    alias_ = get_alias_name(alias)
                    self.imported_modules[alias_] = [alias, False]
            # register from imports
            elif isinstance(subnode, ast.ImportFrom):
                for alias in subnode.names:
                    alias_ = get_alias_name(alias)
                    self.imported_functions[alias_] = [subnode.module, alias, False]
            # register a global
            elif isinstance(subnode, (ast.Assign, ast.AugAssign)):
                targets = assignment_targets(subnode)
                if any((self.spig.globals_used.get(target, False) for target in targets)):
                    self.visit(subnode)
            else:
                #print('Skipping a global %r' % subnode.__class__)
                pass
        imports = self.generate_imports(self.imported_modules, self.imported_functions)
        self.import_lines.extend(imports)
        #return BASE_CLASS.visit_Module(self, node)

    def visit_ImportFrom(self, node, emitCimport=False):
        imp = 'cimport' if emitCimport else 'import'
        if node.module:
            self.statement(node, 'from ', node.level * '.',
                           node.module, ' ' + imp + ' ')
        else:
            self.statement(node, 'from ', node.level * '. ' + imp + ' ')
        self.comma_list(node.names)

    def generate_imports(self, modules, functions):
        imports = []
        for (alias, used_flag) in six.itervalues(modules):
            if used_flag:
                import_line = cyth_helpers.ast_to_sourcecode(ast.Import(names=[alias]))
                imports.append(import_line)
                if alias.name in self.cimport_whitelist:
                    imports.append('c' + import_line)
        for (modulename, alias, used_flag) in six.itervalues(functions):
            # If module
            if used_flag and alias.name not in self.import_from_blacklist:
                impnode = ast.ImportFrom(module=modulename, names=[alias], level=0)
                impsrc  = cyth_helpers.ast_to_sourcecode(impnode)
                imports.append(impsrc)
                # Check if the import is explicitly whitelisted or blacklisted
                whitelisted = any(map(modulename.startswith, self.cimport_whitelist))
                cblacklisted = modulename in self.cimport_blacklist
                if whitelisted and not cblacklisted:
                    temp_cv = CythVisitor()
                    temp_cv.visit_ImportFrom(impnode, emitCimport=True)
                    import_line = temp_cv.get_result()[0]
                    imports.append(import_line)
        for modulename in set(self.modules_to_cimport):
            module_alias = modules.get(modulename, [None])[0]
            if module_alias is not None:
                assert isinstance(module_alias, ast.alias), type(module_alias)
                cythed_alias = deepcopy(module_alias)
                cythed_alias.name = cyth_helpers.get_cyth_name(module_alias.name)
                # short circuit exploit for brevity
                cythed_alias.asname = cythed_alias.asname and cyth_helpers.get_cyth_name(module_alias.asname)
                tmpnode = ast.Import(names=[cythed_alias])
                import_line = 'c' + cyth_helpers.ast_to_sourcecode(tmpnode)
                imports.append(import_line)
        module_func_dict = dict(chain(self.cythonized_funcs.iteritems(),
                                      self.plain_funcs.iteritems()))

        #@utool.show_return_value
        def is_called_in(funcname, node):
            call_list = get_funcalls_in_node(node)
            def _iscalled(call):
                return (isinstance(call, ast.Call) and
                        isinstance(call.func, ast.Name) and
                        funcname == call.func.id)
            return any(map(_iscalled, call_list))
            #def name_of_call(call):  # ast.Node -> string option
            #    #print('ast dump: %r' % ast.dump(call))
            #    if not isinstance(call, ast.Call):
            #        return []
            #    if not isinstance(call.func, ast.Name):
            #        return []
            #    return [call.func.id]
            #is_called = funcname in chain(*map(name_of_call, call_list))
            #return is_called

        called_funcs = []
        print('module_func_dict = %r' % (module_func_dict.keys(),))
        for callee in module_func_dict.keys():
            for (caller, caller_node) in six.iteritems(self.cythonized_funcs):
                if is_called_in(callee, caller_node):
                    called_funcs.append(callee)
        if len(called_funcs) > 0:
            names = [ast.alias(name, None) for name in called_funcs]
            fromimport = ast.ImportFrom(module=self.py_modname, names=names, level=0)
            imports.append(cyth_helpers.ast_to_sourcecode(fromimport))

        return imports

    def visit_Call(self, node):
        """
        Gets called when parser encounters a function call
        """
        #print(ast.dump(node))
        # Special case for functions with _cyth suffix. These should have been
        # generated by us.
        is_cyth_call = lambda name: name.endswith('_cyth') and not name.startswith('_')
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            #print('visit_Call, branch 1')
            if node.func.value.id in self.imported_modules:
                self.imported_modules[node.func.value.id][1] = True
            if is_cyth_call(node.func.attr):
                self.modules_to_cimport.append(node.func.value.id)
                newnode = deepcopy(node)
                newnode.func.attr = '_' + node.func.attr
                newnode.func.value.id = cyth_helpers.get_cyth_name(node.func.value.id)
                return BASE_CLASS.visit_Call(self, newnode)
        if isinstance(node.func, ast.Name):
            #print('visit_Call, branch 2')
            if node.func.id in self.imported_functions:
                self.imported_functions[node.func.id][2] = True
            if is_cyth_call(node.func.id):
                newnode = deepcopy(node)
                newnode.func.id = '_' + node.func.id
                return BASE_CLASS.visit_Call(self, newnode)
        return BASE_CLASS.visit_Call(self, node)

    def visit_str(self, string):
        self.write(string)

    def visit_FunctionDef(self, node):
        """
        Gets called when parser encounters a function definition
        """
        #super(CythVisitor, self).visit_FunctionDef(node)
        new_body = []
        #actiontup = None
        cyth_mode = False  # used for #if/else/endif
        param_typedict = {}
        bodyvars_typedict = {}
        return_type = None
        has_markup = False
        first_docstr = None
        inline_flag_ptr = [False]
        collect_macro_input = False
        macro_input_buffer_ptr = [[]]
        suspended_macro_context_ptr = [None]
        for stmt in node.body:
            if is_docstring(stmt):
                docstr = stmt.value.s
                if first_docstr is None:
                    first_docstr = docstr
                has_markup = has_markup or docstr.find('#if CYTH') != -1
                #actiontup = self.parse_cyth_markup(docstr, funcdef_node=node)
                (source_lines, cyth_mode, collect_macro_input,
                 new_param_typedict, new_bodyvars_typedict,
                 new_return_type) = self.parse_cyth_preproc_markup(
                    docstr, cyth_mode, collect_macro_input,
                    macro_input_buffer_ptr, suspended_macro_context_ptr,
                    inline_flag_ptr)
                #print('source_lines: %r' % (source_lines,))
                new_body.extend(source_lines)
                if new_return_type is not None and return_type is None:
                    return_type = new_return_type
                param_typedict.update(new_param_typedict)
                bodyvars_typedict.update(new_bodyvars_typedict)
            else:
                #print('cyth_mode: %r, stmt: %r' % (cyth_mode, ast.dump(stmt)))
                if not (cyth_mode or collect_macro_input):
                    new_body.append(stmt)
                if collect_macro_input:
                    macro_input_buffer_ptr[0].append(cyth_helpers.ast_to_sourcecode(stmt))
        if has_markup:
            self.cythonized_funcs[node.name] = node
            self.register_benchmark(node.name, first_docstr, self.py_modname)
            union_typedict = {}
            union_typedict.update(param_typedict)
            union_typedict.update(bodyvars_typedict)
            if return_type is None:
                return_type = infer_return_type(node, union_typedict)

            self.newline(extra=1)
            cyth_funcname = cyth_helpers.get_cyth_name(node.name)
            # TODO: should allow for user specification
            func_prefix = utool.unindent('''
            @cython.boundscheck(False)
            @cython.wraparound(False)
            ''').strip()

            # http://docs.cython.org/src/reference/compilation.html#compiler-directives
            # [(name, defaultval), ...]
            cython_compiler_directives = [  # NOQA
                ('boundscheck', True),
                ('wraparound', True),
                ('nonecheck', False),
                ('overflowcheck', False),
                ('overflowcheck.fold', True),  # may help or hurt depending on compiler, arch, and opt settings
                ('embedsignature', False),
                ('cdivision', False),
                ('cdivision_warnings', False),
                ('always_allow_keywords', None),
                ('profile', False),
                ('linetrace', False),
                ('invert_types', None),
                ('language_level', 2),
                ('c_string_type', bytes),
                ('c_string_encoding', 'ascii'),
                ('type_version_tag', True),
                ('unraisable_tracebacks', None),
            ]

            return_string = (" %s " % return_type) if return_type is not None else " "
            self.statement(node, func_prefix + '\n')
            # HACK: indexing is used to extract a portion of the generated stream, which wouldn't
            # be needed if statement/write/etc all returned values rather than writing a stream
            index_before = len(self.result)
            inline_string = ' inline ' if inline_flag_ptr[0] else ''
            self.write('cpdef%s%s%s(' % (inline_string, return_string, cyth_funcname,))
            nonsig_typedict = self.signature(node.args, typedict=union_typedict)
            cyth_def_body = self.typedict_to_cythdef(nonsig_typedict)
            self.write(')')
            function_signature = ''.join(self.result[index_before:])
            self.interface_lines.append(function_signature)
            self.write(':')
            # TODO FIXME: the typedict parser is a giant hack right now.
            # Find a good cython parser
            self.indentation += 1
            #cyth_def_body = self.typedict_to_cythdef(bodyvars_typedict)
            for s in cyth_def_body:
                self.write('\n', s)
            self.write('\n')
            self.indentation -= 1
            self.body(new_body)
        else:
            self.plain_funcs[node.name] = node
#        if actiontup:
#            self.cythonized_funcs[node.name] = node
#            if actiontup[0] == 'defines':
#                _, cyth_def, typedict, return_type = actiontup
#                #self.decorators(node, 2)
#                self.newline(extra=1)
#                cyth_funcname = cyth_helpers.get_cyth_name(node.name)
#                # TODO: should allow for user specification
#                func_prefix = utool.unindent('''
#                @cython.boundscheck(False)
#                @cython.wraparound(False)
#                ''').strip()
#
#                return_string = (" %s " % return_type) if return_type is not None else " "
#                #self.statement(node, func_prefix + '\ncpdef%s%s(' % (return_string, cyth_funcname,))
#                self.statement(node, func_prefix + '\n')
#                # HACK: indexing is used to extract a portion of the generated stream, which wouldn't
#                # be needed if statement/write/etc all returned values rather than writing a stream
#                index_before = len(self.result)
#                self.write('cpdef%s%s(' % (return_string, cyth_funcname,))
#                nonsig_typedict = self.signature(node.args, typedict=typedict)
#                cyth_def_body = self.typedict_to_cythdef(nonsig_typedict)
#                self.write(')')
#                function_signature = ''.join(self.result[index_before:])
#                self.interface_lines.append(function_signature)
#                if getattr(node, 'returns', None) is not None:
#                    self.write(' ->', node.returns)
#                self.write(':')
#                self.indentation += 1
#                for s in cyth_def_body:
#                    self.write('\n', s)
#                self.indentation -= 1
#                self.body(new_body)
#            elif actiontup[0] == 'replace':
#                cyth_def = actiontup[1]
#                self.newline(extra=1)
#                self.write(cyth_def)
#                regex_flags = re.MULTILINE
#                sig_regex = re.compile('(cpdef.*\)):$', regex_flags)
#                match = sig_regex.search(cyth_def)
#                function_signature = match.group(1)
#                self.interface_lines.append(function_signature)
#        else:
#            self.plain_funcs[node.name] = node

    def comma_list(self, items, trailing=False):
        for idx, item in enumerate(items):
            if idx:
                self.write(', ')
            self.visit(item)
        if trailing:
            self.write(',')

    def get_benchmarks(self):
        bench_text = cyth_benchmarks.make_bench_text(self.benchmark_codes,
                                                     self.benchmark_names,
                                                     self.py_modname)
        return bench_text


def is_docstring(node):
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Str)


def assignment_targets(node):
    """
    Assign nodes have a list of multiple targets, which is used for
    'a = b = c' (a and b are both targets)

    'x, y = y, x' has a tuple as the only element of the targets array,
    (likewise for '[x, y] = [y, x]', but with lists)
    """
    assert isinstance(node, (ast.Assign, ast.AugAssign)), type(node)
    if isinstance(node, ast.AugAssign):
        assign_targets = [node.target]
        return assign_targets
    elif isinstance(node, ast.Assign):
        assign_targets = []
        for target in node.targets:
            if isinstance(target, (ast.Tuple, ast.List)):
                assign_targets.extend(target.elts)
            else:
                assign_targets.append(target)
        return assign_targets
    else:
        raise AssertionError('unexpected node type %r' % type(node))


#def parseparen(string):
#    src = cStringIO.StringIO(line3).readline
#    tokentup_list = list(tokenize.generate_tokens(src))
#    token_list = [token[1] for token in tokentup_list]


def parse_cdef_line(line):
    """
    Example:
        >>> from cyth.cyth_script import *  # NOQA
        >>> line1 = 'np.array[float, ndims=2] x, y, z'
        >>> sorted(parse_cdef_line(line1).items())
        [('x', 'np.array[float,ndims=2]'), ('y', 'np.array[float,ndims=2]'), ('z', 'np.array[float,ndims=2]')]
        >>> line2 = 'cdef int x=y, y=2, z=3'
        >>> sorted(parse_cdef_line(line2).items())
        [('x', 'int'), ('y', 'int'), ('z', 'int')]
        >>> line3 = 'cdef np.ndarray[np.float64_t, ndim=1] out = np.zeros((nMats,), dtype=np.float64)'
        >>> sorted(parse_cdef_line(line3).items())
        [('out', 'np.ndarray[np.float64_t, ndim=1]')]
    """
    line = line.replace(' = ', '=')
    tokens = line.replace('cdef ', '').strip().split(' ')
    for ix, token in enumerate(tokens):
        if token.find(",") == -1:
            break
    _type = ''.join(tokens[:ix + 1])
    varnames_split_ = ''.join(tokens[ix + 1:]).split(",")
    varnames_hack_ = []
    lparen = 0
    rparen = 0
    current = ''
    # Not a general solution
    for t in varnames_split_:
        lparen += t.count('(')
        rparen += t.count(')')
        if lparen != rparen:
            current += t + ','
        else:
            current += t
            varnames_hack_.append(current)
            current = ''
    varnames = (x.split('=')[0] for x in varnames_hack_)
    typedict = {varname.strip(): _type.strip() for varname in varnames}
    return typedict


class FirstpassInformationGatherer(ast.NodeVisitor):
    """
    first pass visitor class
    """
    def __init__(self):
        self.global_names = []

    def visit_Module(self, node):
        for subnode in node.body:
            if isinstance(subnode, (ast.Assign, ast.AugAssign)):
                assign_targets = assignment_targets(subnode)
                for target in assign_targets:
                    self.global_names.append(target)


class SecondpassInformationGatherer(ast.NodeVisitor):
    """
    second pass visitor class
    """
    def __init__(self, fpig):
        self.fpig = fpig
        self.globals_used = {name: False for name in fpig.global_names}

    def visit_Name(self, node):
        isname = lambda x: isinstance(x, ast.Name)
        getid = lambda x: x.id
        global_name_iter = map(getid, filter(isname, self.fpig.global_names))
        if getid(node) in global_name_iter and isinstance(node.ctx, ast.Load):
            self.globals_used[node] = True

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name):
            isattribute = lambda x: isinstance(x, ast.Attribute)
            hasloadctx = lambda x: isinstance(x.value, ast.Name) and isinstance(x.value.ctx, ast.Load)
            filt = lambda x: isattribute(x) and hasloadctx(x)
            gettup = lambda x: (x.value.id, x.attr)
            tup_iter = map(gettup, filter(filt, self.fpig.global_names))
            if gettup(node) in tup_iter:
                self.globals_used[node] = True

    def visit_Expr(self, node):
        if isinstance(node.value, ast.Str):
            for global_name_node in self.fpig.global_names:
                # for cyth strings, we don't yet have a good parser, so use
                #  substring as a conservative estimate
                global_name = None
                if isinstance(global_name_node, ast.Name):
                    global_name = global_name_node.id
                elif isinstance(global_name_node, ast.Attribute):
                    global_name = global_name_node.value.id + "." + global_name_node.attr
                self.globals_used[global_name_node] = (self.globals_used.get(global_name_node, False) or
                                                        (node.value.s.find(global_name) != -1))


class CallRecorder(ast.NodeVisitor):
    def __init__(self):
        self.calls = []
    def visit_Call(self, node):
        self.calls.append(node)


def get_funcalls_in_node(node):
    cr = CallRecorder()
    cr.visit(node)
    return cr.calls


def infer_return_type(funcdef_node, typedict):
    class ReturnTypeInferrer(ast.NodeVisitor):
        def __init__(self, node):
            self.return_type = None
            self.visited_returns = []

            assert isinstance(node, ast.FunctionDef), type(node)
            funcdef = node
            self.visit(funcdef)
            #print('visited_returns: %r' % self.visited_returns)
            if utool.list_allsame(self.visited_returns) and len(self.visited_returns) > 0:
                self.return_type = self.visited_returns[0]

        def visit_Return(self, node):
            if node.value:
                if isinstance(node.value, ast.Name):
                    self.visited_returns.append(typedict.get(node.value.id, None))
                elif isinstance(node.value, ast.Tuple):
                    self.visited_returns.append("tuple")

    return ReturnTypeInferrer(funcdef_node).return_type
