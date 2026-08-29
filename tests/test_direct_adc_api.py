from hantek1008c.acquire import DirectADCConfig, SAMPLE_RATES, decode_direct_u12


def test_validated_direct_adc_sample_rate_mapping():
    assert SAMPLE_RATES[0x11] == 800_000.0
    assert SAMPLE_RATES[0x0F] == 2_400_000.0
    assert DirectADCConfig(a3=0x0F).sample_rate == 2_400_000.0


def test_direct_u12_decode_masks_upper_nibble():
    b2 = bytes.fromhex("05 F8 01 10")
    b3 = bytes.fromhex("FF 0F")
    assert decode_direct_u12((b2, b3)) == [0x805, 0x001, 0xFFF]


def test_trigger_config_defaults_preserve_existing_wire_values():
    cfg = DirectADCConfig()
    assert cfg.trigger_enabled is False
    assert cfg.trigger_slope_raw == 0
    assert cfg.trigger_level_adc == 0x0800
    assert cfg.auto_timeout_ms == 1870.0


def test_trigger_raw_validation_uses_only_proven_selector_domain():
    # Validation is exercised without hardware by borrowing the unbound method
    # and a tiny fake session whose _tx records payloads.
    from hantek1008c.acquire import DirectADCSession

    class Fake:
        def __init__(self):
            self.sent = []
            self.config = DirectADCConfig()
        def _tx(self, payload):
            self.sent.append(payload)
            return b""

    fake = Fake()
    DirectADCSession.set_trigger_slope_raw(fake, 1)
    assert fake.sent[-1] == bytes.fromhex("C1 00 01")
    assert fake.config.trigger_slope_raw == 1

    DirectADCSession.set_trigger_level_adc(fake, 0x07CB)
    assert fake.sent[-1] == bytes.fromhex("AB 07 CB")
    assert fake.config.trigger_level_adc == 0x07CB


def test_trigger_slope_named_mapping_is_proven_from_windows_chronology():
    from hantek1008c.acquire import DirectADCSession

    class Fake:
        def __init__(self):
            self.sent = []
            self.config = DirectADCConfig()
        def _tx(self, payload):
            self.sent.append(payload)
            return b""
        def set_trigger_slope_raw(self, value):
            return DirectADCSession.set_trigger_slope_raw(self, value)

    fake = Fake()
    DirectADCSession.set_trigger_slope(fake, "rising")
    assert fake.sent[-1] == bytes.fromhex("C1 00 00")
    DirectADCSession.set_trigger_slope(fake, "+")
    assert fake.sent[-1] == bytes.fromhex("C1 00 00")
    DirectADCSession.set_trigger_slope(fake, "falling")
    assert fake.sent[-1] == bytes.fromhex("C1 00 01")
    DirectADCSession.set_trigger_slope(fake, "-")
    assert fake.sent[-1] == bytes.fromhex("C1 00 01")
