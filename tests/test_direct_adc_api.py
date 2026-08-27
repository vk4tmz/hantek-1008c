from hantek1008c.acquire import DirectADCConfig, SAMPLE_RATES, decode_direct_u12


def test_validated_direct_adc_sample_rate_mapping():
    assert SAMPLE_RATES[0x11] == 800_000.0
    assert SAMPLE_RATES[0x0F] == 2_400_000.0
    assert DirectADCConfig(a3=0x0F).sample_rate == 2_400_000.0


def test_direct_u12_decode_masks_upper_nibble():
    b2 = bytes.fromhex("05 F8 01 10")
    b3 = bytes.fromhex("FF 0F")
    assert decode_direct_u12((b2, b3)) == [0x805, 0x001, 0xFFF]
