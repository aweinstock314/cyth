from __future__ import absolute_import, division, print_function
import utool

#DEFAULT_ON = False
DEFAULT_ON = True
DYNAMIC = not utool.get_flag('--nodyn')
WITH_CYTH = not utool.get_flag('--nocyth') if DEFAULT_ON else utool.get_flag('--cyth')
CYTH_WRITE = utool.get_flag('--cyth-write')
