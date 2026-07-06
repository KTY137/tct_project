import numpy as np
import pytest

from devices.oscilloscope import Oscilloscope


def test_parse_waveform_tektronix_key_value_preamble() -> None:
    scope = Oscilloscope(simulation=True)
    raw = np.array([127.0, 177.0], dtype=float)
    pre = (
        'BYT_Nr 1;NR_Pt 2;XINcr 4.0E-7;XZEro -1.0E-3;'
        'YMUlt 2.0E-2;YOFf 127.0;YZEro 0.0;YUNit "V"'
    )

    t, v = scope._parse_waveform(raw, pre)

    assert t[0] == pytest.approx(-1.0e-3)
    assert t[1] == pytest.approx(-1.0e-3 + 4.0e-7)
    assert v[0] == pytest.approx(0.0)
    assert v[1] == pytest.approx(1.0)


def test_parse_waveform_standard_scpi_csv_preamble() -> None:
    scope = Oscilloscope(simulation=True)
    raw = np.array([127.0, 177.0], dtype=float)
    # FORMAT,TYPE,POINTS,COUNT,XINCREMENT,XORIGIN,XREFERENCE,
    # YINCREMENT,YORIGIN,YREFERENCE
    pre = "0,1,2,1,4.0E-7,-1.0E-3,0,2.0E-2,0.0,127.0"

    t, v = scope._parse_waveform(raw, pre)

    assert t[0] == pytest.approx(-1.0e-3)
    assert t[1] == pytest.approx(-1.0e-3 + 4.0e-7)
    assert v[0] == pytest.approx(0.0)
    assert v[1] == pytest.approx(1.0)


def test_parse_waveform_tektronix_semicolon_positional_preamble() -> None:
    scope = Oscilloscope(simulation=True)
    raw = np.array([0.0, 5.0], dtype=float)
    pre = (
        '1;8;BINARY;RI;MSB;"Ch1, DC coupling, 5.000V/div";2000;Y;"s";'
        '1.0000E-9;-1.0000E-6;0;"V";200.0000E-3;0.0E+0;0.0E+0;2000;2000000000'
    )

    t, v = scope._parse_waveform(raw, pre)

    assert t[0] == pytest.approx(-1.0e-6)
    assert t[1] == pytest.approx(-1.0e-6 + 1.0e-9)
    assert v[0] == pytest.approx(0.0)
    assert v[1] == pytest.approx(1.0)


def test_parse_waveform_tektronix_positional_nonzero_yoff_yzero() -> None:
    """Regression: YOFf (field 14) and YZEro (field 15) must not be swapped.

    Modelled on the lab TBS1052C's real WFMPRE? (YMUlt=0.08, YOFf=-7.5,
    YZEro=0) where the two fields differ, so a swap changes the result.
    Tektronix formula: volts = (raw - YOFf) * YMUlt + YZEro.
    """
    scope = Oscilloscope(simulation=True)
    raw = np.array([0.0, 100.0], dtype=float)
    ymult, yoff, yzero = 80.0000e-3, -7.5000, 0.5000
    pre = (
        '1;8;BINARY;RI;MSB;"Ch1, DC coupling, 2.000V/div";2000;Y;"s";'
        f'3.2000E-6;-3.2000E-3;0;"V";{ymult:.4E};{yoff:.4E};{yzero:.4E};'
        '2000;200000000'
    )

    t, v = scope._parse_waveform(raw, pre)

    # Correct: volts = (raw - YOFf)*YMUlt + YZEro.
    assert v[0] == pytest.approx((0.0 - yoff) * ymult + yzero)      # 1.10 V
    assert v[1] == pytest.approx((100.0 - yoff) * ymult + yzero)    # 9.10 V
    # Under a YOFf/YZEro swap these would be -7.54 V and 0.46 V — both asserts fail.
