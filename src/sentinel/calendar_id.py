"""Jember demand calendar: the city's fuel demand has a pulse.

Separate from holidays (forecast.py handles those), these are
recurring LOCAL demand patterns, each small, documented, and honest
about being estimated patterns rather than measured statistics:

- Payday window (25th to the 2nd): salaries land, tanks get filled,
  retail fuel demand rises. Boost +2.
- Javanese pasaran cycle: market days rotate on the 5-day pasaran
  (Legi, Pahing, Pon, Wage, Kliwon) anchored on a verifiable epoch -
  17 August 1945 was Jumat Legi. Market towns around Jember trade
  hardest on their pasaran day; the city-wide average effect is a
  small +1 on Legi and Pahing (the historically busiest market
  days in the region) - deliberately the weakest factor here.
- Harvest seasons: tobacco (roughly Aug-Oct) and coffee (Jul-Sep)
  put cash and transport demand into the plantation belt east and
  north of the city; rice harvests (Mar-Apr, Aug-Sep) do the same
  regency-wide. Boost +2 in those months.
- Campus terms: Mastrip-area stations serve UNEJ/Polije; the first
  three weeks of the odd semester (mid-Aug to early Sep) and the
  January return spike student fuel demand near campus. Boost +2
  (city-wide effect small, station-level effect real).

Total demand boost is capped at +5 in the forecast so the calendar
can tilt a borderline day but never manufacture a crisis alone.
"""
from datetime import date

PASARAN = ["Legi", "Pahing", "Pon", "Wage", "Kliwon"]
EPOCH = date(1945, 8, 17)  # Jumat Legi (documented)


def pasaran_of(day):
    return PASARAN[(day - EPOCH).days % 5]


def demand_factors(day):
    """-> (boost:int, reasons:[str]) for a datetime.date."""
    boost, reasons = 0, []
    if day.day >= 25 or day.day <= 2:
        boost += 2
        reasons.append("masa gajian")
    p = pasaran_of(day)
    if p in ("Legi", "Pahing"):
        boost += 1
        reasons.append(f"pasaran {p}")
    months_harvest = {3, 4, 7, 8, 9, 10}
    if day.month in months_harvest:
        boost += 2
        reasons.append("musim panen")
    if (day.month == 8 and day.day >= 10) or (day.month == 9 and day.day <= 10) \
            or (day.month == 1 and 5 <= day.day <= 20):
        boost += 2
        reasons.append("masa awal kuliah")
    return min(boost, 5), reasons
