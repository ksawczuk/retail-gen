"""Unit tests for add_customers: new customers' logins stay unique against the existing customers and the batch.
Builds real customers at a small scale and forces the clashes by setting the new people's logins; run with
python -m unittest"""
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from retailgen.config import Config
from retailgen.truth import customers as customers_module
from retailgen.truth.customers import add_customers, generate_customers

NS = "datetime64[ns]"
REAL_PEOPLE = customers_module._people


class NewLoginsUniqueTest(unittest.TestCase):
    """Two existing customers hold a login that a new person draws, and two new people share one."""

    def setUp(self):
        """Give the first two existing customers known logins, then build the batch of four new signups."""
        self.cfg = Config(scale=0.01)
        self.rng = np.random.default_rng(3)
        self.customers, self.addresses = generate_customers(self.cfg, self.rng)
        self.customers.loc[self.customers.index[0], "email"] = "dana.smith@example.com"
        self.customers.loc[self.customers.index[1], "email"] = "dana.smith1@example.com"
        self.times = (np.full(4, np.datetime64("2026-10-05T12:00:00", "ns"))).astype(NS)

    def _batch_logins(self, logins):
        """Run add_customers with the four new people's logins set to `logins`, and return the result."""
        def people_with_logins(*args, **kwargs):
            """Call the real people builder, then set the logins under test."""
            people = REAL_PEOPLE(*args, **kwargs)
            people["email"] = logins
            return people

        with mock.patch.object(customers_module, "_people", side_effect=people_with_logins):
            out, _, _ = add_customers(self.cfg, self.rng, self.customers, self.addresses, self.times)
        return out

    def test_new_login_matching_an_existing_one_is_renamed_to_a_free_one(self):
        """A new person whose login is taken by an existing customer gets a login no customer has."""
        out = self._batch_logins(["dana.smith@example.com", "dana.smith@example.com",
                                  "kai.wong@example.com", "lee.chan@example.com"])
        self.assertEqual(int(out["email"].duplicated().sum()), 0)

    def test_two_new_people_with_the_same_login_do_not_share_it(self):
        """Two people in the same batch who draw one login end up with two different logins."""
        out = self._batch_logins(["kai.wong@example.com", "kai.wong@example.com",
                                  "lee.chan@example.com", "lee.chan@example.com"])
        self.assertEqual(int(out["email"].duplicated().sum()), 0)

    def test_existing_logins_are_left_as_they_were(self):
        """Only the new people's logins change; every existing customer keeps its login."""
        before = dict(zip(self.customers["customer_id"], self.customers["email"]))
        out = self._batch_logins(["dana.smith@example.com", "dana.smith@example.com",
                                  "kai.wong@example.com", "lee.chan@example.com"])
        after = dict(zip(out["customer_id"], out["email"]))
        self.assertEqual({cid: after[cid] for cid in before}, before)


if __name__ == "__main__":
    unittest.main()
