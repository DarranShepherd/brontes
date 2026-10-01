import unittest
from datetime import datetime, timezone

from brontes.myenergi_control import MyEnergiTimedBoosts

UTC = timezone.utc


class MyEnergiTimedBoostsTests(unittest.TestCase):
    def test_replaces_empty_slots_and_waits_for_each_write_to_be_visible(self) -> None:
        slots = {number: {'slt': number, 'bsh': 0, 'bsm': 0, 'bdh': 0, 'bdm': 0, 'bdd': '00000000'} for number in range(11, 15)}
        calls = []

        def request(path):
            calls.append(path)
            if path == 'cgi-jstatus-Z':
                return {'zappi': [{'sno': 123, 'zmo': 3, 'cmt': 254}]}
            if path == 'cgi-boost-time-Z123':
                return {'boost_times': list(slots.values())}
            _, number, start, duration, days = path.rsplit('-', 4)
            slot = int(number)
            slots[slot] = {
                'slt': slot, 'bsh': int(start[:2]), 'bsm': int(start[2:]),
                'bdh': int(duration[:-2]), 'bdm': int(duration[-2:]), 'bdd': days,
            }
            return {'status': 'ok'}

        writer = MyEnergiTimedBoosts(request=request, sleep=lambda _: None)
        writer.replace((
            datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
            datetime(2026, 10, 1, 12, 30, tzinfo=UTC),
            datetime(2026, 10, 1, 14, 0, tzinfo=UTC),
        ))

        self.assertIn('cgi-boost-time-Z123-11-1200-100-00001000', calls)
        self.assertEqual(slots[11], {'slt': 11, 'bsh': 12, 'bsm': 0, 'bdh': 1, 'bdm': 0, 'bdd': '00001000'})
        self.assertEqual(slots[12], {'slt': 12, 'bsh': 14, 'bsm': 0, 'bdh': 0, 'bdm': 30, 'bdd': '00001000'})


if __name__ == '__main__':
    unittest.main()
