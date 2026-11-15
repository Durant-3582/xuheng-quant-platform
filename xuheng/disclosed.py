"""Resolve report vintages using only the information disclosed at each signal."""
from itertools import groupby


def revisions(raw):
    out = []
    for (period, ann), snapshots in groupby(sorted(raw, key=lambda r: (r[0], r[1])), key=lambda r: (r[0], r[1])):
        # An update flag alone does not date a restatement. Where versions
        # carry the same announcement date, use only unambiguous field values.
        rows = [r[3:] for r in snapshots]
        values = []
        for col in zip(*rows):
            known = {x for x in col if x is not None}
            values.append(known.pop() if len(known)==1 else None)
        out.append([period, ann, *values])
    return out


def latest(vintages, asof):
    by_period = {}
    for row in vintages:
        if row[1] <= asof and row[0] <= row[1]:
            by_period[row[0]] = row
    return [by_period[k] for k in sorted(by_period, reverse=True)]


def annual_roe(vintages, signals):
    events = sorted((r for r in vintages if r[0].endswith('1231')), key=lambda r: (r[1], r[0]))
    pos, current, result = 0, None, {}
    for day in signals:
        while pos < len(events) and events[pos][1] <= day:
            row = events[pos]
            if current is None or row[0] >= current[0]:
                current = row
            pos += 1
        if current:
            age = (int(day[:4])-int(current[0][:4]))*12 + int(day[4:6])-12
            if 0 <= age <= 18 and current[3] is not None:
                result[day] = current
    return result
