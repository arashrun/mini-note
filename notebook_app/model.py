from dataclasses import dataclass, field
from uuid import uuid4


PAPER_STYLES = ("plain", "ruled", "grid")


@dataclass
class Page:
    id: str = field(default_factory=lambda: uuid4().hex)
    title: str = ""
    body: str = ""
    manual: bool = True


@dataclass
class Book:
    pages: list[Page] = field(default_factory=lambda: [Page(), Page()])
    paper_style: str = "ruled"
    images: dict[str, bytes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.ensure_spread()

    def ensure_spread(self) -> None:
        while len(self.pages) > 2 and not self.pages[-1].manual and not self.pages[-1].title and not self.pages[-1].body.strip():
            self.pages.pop()
        if not self.pages:
            self.pages.append(Page())
        if len(self.pages) % 2:
            self.pages.append(Page(manual=False))

    def insert_page(self, index: int) -> Page:
        page = Page()
        self.pages.insert(index + 1, page)
        self.ensure_spread()
        return page

    def remove_page(self, index: int) -> None:
        del self.pages[index]
        self.ensure_spread()

    def chapters(self) -> list[tuple[int, str]]:
        return [(index, page.title.strip()) for index, page in enumerate(self.pages) if page.title.strip()]
