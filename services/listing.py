"""Search, sort and filter for the record lists.

Every page that accumulates rows needs the same three things, and they were
built ad hoc: products had a search box, the audit log had filters, and sales -
the list that grows fastest - had neither. A wholesaler doing 60 sales a day
fills fifteen pages in a week, and the only way to find one was to page through.

The rules that matter here:

- **Sort keys are whitelisted.** A sort column arriving in the query string is
  user input. Mapping a key to a column server-side means an unknown key falls
  back to the default rather than reaching the database.
- **Filters compose.** Searching, then filtering, then sorting, then paging has
  to survive every combination, including page 4 of a filtered search.
- **Nothing is remembered.** The URL is the whole state, so a filtered list can
  be bookmarked, shared, or reloaded without surprises.
"""
from flask import request

from extensions import db


def search_term(arg='q'):
    """The trimmed search string, or '' when absent."""
    return (request.args.get(arg, '') or '').strip()


def apply_search(query, term, columns):
    """Filter `query` to rows where any of `columns` contains `term`.

    Case-insensitive substring, because users search for the middle of a name
    ("aqua") at least as often as the start.
    """
    if not term or not columns:
        return query
    pattern = f'%{term}%'
    return query.filter(db.or_(*[column.ilike(pattern) for column in columns]))


def sort_key(options, default, arg='sort'):
    """The requested sort key if it is one we offer, otherwise `default`.

    Never trust the query string to name a column. An unrecognised key is not an
    error worth showing anyone - it silently becomes the default.
    """
    requested = (request.args.get(arg, '') or '').strip()
    return requested if requested in options else default


def apply_sort(query, options, key):
    """Order `query` by the whitelisted `key`.

    `options` maps a key to a list of ORDER BY expressions, so a sort can be
    compound - "biggest first, then newest" - without the caller repeating it.
    """
    return query.order_by(*options[key])


def filter_value(name, allowed):
    """A query-string filter value, or '' unless it is one we recognise."""
    value = (request.args.get(name, '') or '').strip()
    return value if value in allowed else ''


def preserved_args(*drop):
    """Current query args minus `drop`, for building links that keep context.

    Paging through a filtered search must not silently discard the filter, and
    changing the sort must not throw you back to page one of everything.
    """
    return {k: v for k, v in request.args.items(multi=False)
            if k not in drop and v not in (None, '')}


def is_filtered(*names):
    """True when any of `names` is set - so an empty list can say why."""
    return any((request.args.get(n, '') or '').strip() for n in names)
