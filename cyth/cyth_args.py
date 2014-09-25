from __future__ import absolute_import, division, print_function
import utool

#DEFAULT_ON = False
DEFAULT_ON = True
DYNAMIC = not utool.get_argflag('--nodyn')
WITH_CYTH = not utool.get_argflag('--nocyth') if DEFAULT_ON else utool.get_argflag('--cyth')
CYTH_WRITE = utool.get_argflag('--cyth-write')
