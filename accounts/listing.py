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


class ListToolbarMixin:
    search_fields = ()
    search_placeholder = "Search"
    sort_options = {}  # key -> (label, ordering tuple)
    default_sort = None

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
            **self.get_extra_toolbar_context(),
        }
        return context
