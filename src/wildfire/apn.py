"""LA County assessor parcel numbers.

The county writes the same number two ways: the AIN, 10 digits ("4420030015"), and the APN with dashes
("4420-030-015", book-page-parcel). DINS uses the 10-digit form. Everything is normalized to the 10 digits.
"""
import re

import pandas as pd


def normalize_apn(value):
    """10-digit AIN string, or None if the value doesn't hold exactly 10 digits."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    digits = re.sub(r"\D", "", str(value))
    return digits if len(digits) == 10 else None
