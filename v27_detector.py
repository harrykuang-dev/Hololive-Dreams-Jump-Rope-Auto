"""Final V27 detector: frozen speed2 + snap_clock, without trial modules."""
from repair_detector import factory

VisualPassDetector = factory('snap_clock')
