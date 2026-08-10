"""화면 문구 번역 — 한국어 / 영어(기본값).

방식은 gettext 와 같다. **소스에 적힌 한국어 문장이 곧 키**이고, 영어는
`EN` 표에서 찾는다. 표에 없으면 한국어를 그대로 돌려주므로, 번역이 빠져도
문구가 사라지지 않는다 (빈 화면보다 낫다).

    from ..core.i18n import tr
    label.setText(tr("연결"))
    self.set_status(tr("{0}개 포트 연결됨").format(count))

인자가 들어가는 문장은 f-string 대신 `tr("… {0} …").format(...)` 로 쓴다 —
f-string 은 값이 박힌 뒤라 키로 쓸 수 없다.
"""

from __future__ import annotations

LANGUAGES = {"ko": "한국어", "en": "English"}
DEFAULT_LANGUAGE = "en"

_current = DEFAULT_LANGUAGE


def set_language(lang: str) -> str:
    """반환값 = 실제로 적용된 언어 코드 (모르는 값이면 기본값)."""
    global _current
    _current = lang if lang in LANGUAGES else DEFAULT_LANGUAGE
    return _current


def current_language() -> str:
    return _current


def tr(text: str) -> str:
    if _current == "ko":
        return text
    return CATALOG.get(_current, {}).get(text, text)


# --------------------------------------------------------------------- 영어 표
from .i18n_en import EN  # noqa: E402 - 표가 커서 파일을 나눴다

CATALOG = {"en": EN}


def missing_keys(keys) -> list[str]:
    """번역이 빠진 키 목록 — selftest 가 이걸로 누락을 잡는다."""
    return sorted(k for k in keys if k not in EN)
