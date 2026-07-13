"""Sensor-pose vision package (E7b).

Optional-dependency sibling of ``analysis/`` (see ``docs/ARCHITECTURE.md``
"vision/" row and ``docs/research/sensor_alignment_cv.md``): ArUco fiducial
detection + 2D rigid/similarity pose estimation for the "bonding-machine
style" sensor alignment beat. Requires ``opencv-python-headless`` (pinned in
``requirements.txt``), which is NOT part of the numpy-pure ``analysis/``
layer contract (``tests/test_layer_contracts.py``) and is imported lazily —
importing this package (or ``vision.sensor_align``) never requires ``cv2`` to
be installed; only calling its detection/pose functions does. Use
``vision.sensor_align.is_available()`` to probe capability first.

No GUI, no device/motion imports here — pure numpy-image-in,
dataclass-result-out functions. The E7c alignment UI (a later beat) consumes
these numbers; it must never gain the ability to command motion through this
package.
"""
from __future__ import annotations
