"""H01-H10 section metadata. Content lives entirely in Kodi string resources."""
from dataclasses import dataclass


@dataclass(frozen=True)
class HelpSection:
    section_id: str
    title_id: int
    body_id: int


SECTIONS = tuple(HelpSection('H%02d' % (i + 1), 32200 + i, 32300 + i)
                 for i in range(10))


def section_index(section_id):
    for i, section in enumerate(SECTIONS):
        if section.section_id == section_id:
            return i
    raise ValueError('unsupported help section')
