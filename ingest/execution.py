"""Shared execution assumptions for research built from daily quotations."""

def opening_flags(opening, reference):
    """A conservative price-band proxy at the opening print; never inspect intraday high/low."""
    price = int(opening*100 + .5000001)
    ref = int(reference*100 + .5000001)
    # With no historical ST labels or exchange limit-price series, a match to any standard
    # band is conservatively blocked on that side. Compare integer cents with half-up rounding.
    up = any(price == (ref*(100+band)+50)//100 for band in (5,10,20,30))
    down = any(price == (ref*(100-band)+50)//100 for band in (5,10,20,30))
    return int(not (price>ref and up)) | (int(not (price<ref and down)) << 1)
