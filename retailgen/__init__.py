"""Synthetic, deliberately dirty retail dataset generator for a Databricks medallion tutorial."""
import pandas as pd

# pandas 3 stores strings as Arrow arrays by default; the generator walks many rows in Python,
# where plain object strings are several times faster.
try:
    pd.set_option("future.infer_string", False)
except (KeyError, pd.errors.OptionError):
    pass
