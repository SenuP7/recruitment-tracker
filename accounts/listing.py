"""Shared list-page behaviour: stage tabs with live counts, search, and sort.

Subclasses describe their tabs, searchable fields, and sort options; the mixin
applies them in a fixed order -- search and extra filters first, then the tab --
so every tab's count reflects the current search but not the other tabs.
Counts come from a single aggregate query rather than one COUNT per tab.
"""

from dataclasses import dataclass

from django.db.models import Count, Q


@dataclass(frozen=True)
class Tab:
    key: str
    label: str
    filter: Q | None = None


# A deliberate ceiling on an export. Nothing here should ever produce a file
# this large, so hitting it means something is wrong -- better a truncated
# file than a request that ties up a worker on a t3.micro.
EXPORT_ROW_LIMIT = 5000

# Excel and Sheets treat a leading =, +, - or @ as the start of a formula, so
# a value a candidate typed could run when someone opens the file. Prefixing
# with an apostrophe makes it text again.
FORMULA_PREFIXES = (chr(61), chr(43), chr(45), chr(64), chr(9), chr(13))  # = + - @ tab cr


def _csv_safe(value):
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


class ListToolbarMixin:
    search_fields = ()
    search_placeholder = "Search"
    sort_options = {}  # key -> (label, ordering tuple)
    default_sort = None

    # ((column heading, attribute path or callable), ...). Left empty, the
    # list simply doesn't offer an export and ?export=csv is ignored.
    export_columns = ()
    export_filename = "export"

    def render_to_response(self, context, **response_kwargs):
        if self.export_columns and self.request.GET.get("export") == "csv":
            return self._csv_response()
        return super().render_to_response(context, **response_kwargs)

    def _csv_response(self):
        """Exports exactly what the list is showing.

        Built from self.get_queryset(), so the search, the active tab and any
        queryset-level access scoping the view applies are all inherited. An
        export that widened access would be a quiet way around the whole
        permission model.
        """
        import csv

        from django.http import HttpResponse
        from django.utils import timezone

        response = HttpResponse(content_type="text/csv")
        stamp = timezone.now().strftime("%Y-%m-%d")
        response["Content-Disposition"] = (
            f'attachment; filename="{self.export_filename}-{stamp}.csv"'
        )

        writer = csv.writer(response)
        writer.writerow([heading for heading, _ in self.export_columns])
        for obj in self.get_queryset()[:EXPORT_ROW_LIMIT]:
            writer.writerow([_csv_safe(self._export_value(obj, a)) for _, a in self.export_columns])
        return response

    @staticmethod
    def _export_value(obj, accessor):
        if callable(accessor):
            return accessor(obj)
        value = obj
        for part in accessor.split("."):
            value = getattr(value, part, None)
            if value is None:
                return ""
        return value() if callable(value) else value

    def get_base_queryset(self):
        raise NotImplementedError

    def get_tabs(self):
        return [Tab("all", "All")]

    def apply_extra_filters(self, queryset):
        return queryset

    def get_extra_toolbar_context(self):
        return {}

    def _apply_search(self, queryset):
        query = self.request.GET.get("q", "").strip()
        self.search_query = query
        # AND across words, OR across fields per word -- same rule as the
        # dashboard and global search, so "Jane Doe" matches split names.
        for term in query.split():
            term_q = Q()
            for field in self.search_fields:
                term_q |= Q(**{f"{field}__icontains": term})
            queryset = queryset.filter(term_q)
        return queryset

    def get_queryset(self):
        queryset = self.apply_extra_filters(self._apply_search(self.get_base_queryset()))
        self._pre_tab_queryset = queryset

        self._tabs = self.get_tabs()
        requested = self.request.GET.get("tab", "")
        self.active_tab = next((t for t in self._tabs if t.key == requested), self._tabs[0])
        if self.active_tab.filter is not None:
            queryset = queryset.filter(self.active_tab.filter)

        requested_sort = self.request.GET.get("sort", "")
        self.active_sort = requested_sort if requested_sort in self.sort_options else self.default_sort
        if self.active_sort:
            queryset = queryset.order_by(*self.sort_options[self.active_sort][1])
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        aggregates = {
            f"t{index}": Count("pk", filter=tab.filter) if tab.filter is not None else Count("pk")
            for index, tab in enumerate(self._tabs)
        }
        counts = self._pre_tab_queryset.order_by().aggregate(**aggregates)
        context["toolbar"] = {
            "tabs": [
                {
                    "key": tab.key,
                    "label": tab.label,
                    "count": counts[f"t{index}"],
                    "active": tab.key == self.active_tab.key,
                }
                for index, tab in enumerate(self._tabs)
            ],
            "active_tab": self.active_tab.key,
            "query": self.search_query,
            "search_placeholder": self.search_placeholder,
            "sort_options": [(key, label) for key, (label, _) in self.sort_options.items()],
            "active_sort": self.active_sort,
            "can_export": bool(self.export_columns),
            **self.get_extra_toolbar_context(),
        }
        return context
