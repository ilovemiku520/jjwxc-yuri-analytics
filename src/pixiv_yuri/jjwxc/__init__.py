"""JJWXC public-metadata research domain.

The legacy package name is retained during the source migration so the existing
database, safety gates, and deployment tooling keep working. New product-facing
code should use this JJWXC namespace.
"""

from pixiv_yuri.jjwxc.models import JjwxcNovel, JjwxcNovelCandidate, JjwxcTrendPoint

__all__ = ["JjwxcNovel", "JjwxcNovelCandidate", "JjwxcTrendPoint"]
