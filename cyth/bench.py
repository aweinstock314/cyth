from __future__ import absolute_import, division, print_function
import timeit

def run_benchmark_get_invVR_mats_sqrd_scale(iterations):
    test_tuples = (['get_invVR_mats_sqrd_scale(invVRs)\n'], ['_get_invVR_mats_sqrd_scale_cyth(invVRs)'])
    setup_script = '''from vtool.keypoint import  *
np.random.seed(0)
invVRs = np.random.rand(4, 3, 3).astype(np.float64)
'''
    time_line = lambda line: timeit.timeit(stmt=line, setup=setup_script, number=iterations)
    time_pair = lambda x, y: (time_line(x), time_line(y))
    def print_timing_info(tup):
        (x, y) = time_pair(tup)
        print("Time for %d iterations of the python version: %d" % (iterations, x))
        print("Time for %d iterations of the cython version: %d" % (iterations, y))
        return (x, y)
    return list(map(print_timing_info, test_tuples))



def run_benchmark_rectify_invV_mats_are_up(iterations):
    test_tuples = ([], [])
    setup_script = ''''''
    time_line = lambda line: timeit.timeit(stmt=line, setup=setup_script, number=iterations)
    time_pair = lambda x, y: (time_line(x), time_line(y))
    def print_timing_info(tup):
        (x, y) = time_pair(tup)
        print("Time for %d iterations of the python version: %d" % (iterations, x))
        print("Time for %d iterations of the cython version: %d" % (iterations, y))
        return (x, y)
    return list(map(print_timing_info, test_tuples))


def run_all_benchmarks(iterations):
    run_benchmark_get_invVR_mats_sqrd_scale(interations)
    run_benchmark_rectify_invV_mats_are_up(interations)
