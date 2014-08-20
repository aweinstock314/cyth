"""
python -c "import doctest, cyth; print(doctest.testmod(cyth.cyth_decorators))"
"""
from __future__ import absolute_import, division, print_function

MACRO_EXPANDERS_DICT = {}
def macro(expander):
    global MACRO_EXPANDERS_DICT
    from utool.util_six import get_funcname
    MACRO_EXPANDERS_DICT[get_funcname(expander)] = expander
    return expander
