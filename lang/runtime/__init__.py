"""Runtime: values, scheduler, tasks, channels, resources and the evaluator."""
import sys

# `Int` is arbitrary precision (V3 7.3.3): lift CPython's 4300-digit limit on
# int<->str conversion so printing or parsing big Ints never leaks a ValueError (BUG-0019).
if hasattr(sys, "set_int_max_str_digits"):
    sys.set_int_max_str_digits(0)
