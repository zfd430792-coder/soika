"""Валидаторы значений конфига.

Каждый валидатор умеет две вещи: проверить значение (``validate``) и рассказать
о себе человеку (``doc``) — на этом построен редактор конфигов ``.cfg``.
"""

from __future__ import annotations

import re
import typing
from urllib.parse import urlparse

BOOL_TRUE = {"1", "true", "yes", "y", "да", "вкл", "on", "+"}
BOOL_FALSE = {"0", "false", "no", "n", "нет", "выкл", "off", "-"}


class ValidationError(ValueError):
    """Значение не подходит — текст ошибки показывается пользователю."""


class Validator:
    """Базовый валидатор: пропускает всё."""

    def __init__(self, doc: dict[str, str] | None = None) -> None:
        self.doc = doc or {"ru": "любое значение", "en": "any value"}

    def validate(self, value: typing.Any) -> typing.Any:
        return value

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.doc.get('ru')}>"


class Boolean(Validator):
    def __init__(self) -> None:
        super().__init__({"ru": "да / нет", "en": "boolean"})

    def validate(self, value: typing.Any) -> bool:
        if isinstance(value, bool):
            return value

        text = str(value).strip().lower()

        if text in BOOL_TRUE:
            return True

        if text in BOOL_FALSE:
            return False

        raise ValidationError(f"«{value}» — это не да/нет")


class Integer(Validator):
    def __init__(self, *, minimum: int | None = None, maximum: int | None = None) -> None:
        self.minimum = minimum
        self.maximum = maximum

        bounds = []

        if minimum is not None:
            bounds.append(f"от {minimum}")

        if maximum is not None:
            bounds.append(f"до {maximum}")

        super().__init__(
            {
                "ru": " ".join(["целое число", *bounds]),
                "en": " ".join(["integer", *bounds]),
            }
        )

    def validate(self, value: typing.Any) -> int:
        try:
            value = int(str(value).strip())
        except (TypeError, ValueError):
            raise ValidationError(f"«{value}» — это не целое число") from None

        if self.minimum is not None and value < self.minimum:
            raise ValidationError(f"Число должно быть не меньше {self.minimum}")

        if self.maximum is not None and value > self.maximum:
            raise ValidationError(f"Число должно быть не больше {self.maximum}")

        return value


class Float(Validator):
    def __init__(self, *, minimum: float | None = None, maximum: float | None = None) -> None:
        self.minimum = minimum
        self.maximum = maximum
        super().__init__({"ru": "дробное число", "en": "float"})

    def validate(self, value: typing.Any) -> float:
        try:
            value = float(str(value).strip().replace(",", "."))
        except (TypeError, ValueError):
            raise ValidationError(f"«{value}» — это не число") from None

        if self.minimum is not None and value < self.minimum:
            raise ValidationError(f"Число должно быть не меньше {self.minimum}")

        if self.maximum is not None and value > self.maximum:
            raise ValidationError(f"Число должно быть не больше {self.maximum}")

        return value


class String(Validator):
    def __init__(self, *, length: int | None = None, min_len: int = 0, max_len: int = 0) -> None:
        self.length = length
        self.min_len = min_len
        self.max_len = max_len
        super().__init__({"ru": "строка", "en": "string"})

    def validate(self, value: typing.Any) -> str:
        value = str(value)

        if self.length is not None and len(value) != self.length:
            raise ValidationError(f"Длина строки должна быть ровно {self.length}")

        if self.min_len and len(value) < self.min_len:
            raise ValidationError(f"Строка короче {self.min_len} символов")

        if self.max_len and len(value) > self.max_len:
            raise ValidationError(f"Строка длиннее {self.max_len} символов")

        return value


class RegExp(Validator):
    def __init__(self, regex: str, flags: int = 0, description: str | None = None) -> None:
        self.regex = re.compile(regex, flags)
        super().__init__(
            {
                "ru": description or f"строка по шаблону {regex}",
                "en": description or f"string matching {regex}",
            }
        )

    def validate(self, value: typing.Any) -> str:
        value = str(value)

        if not self.regex.match(value):
            raise ValidationError(f"«{value}» не подходит под шаблон")

        return value


class Choice(Validator):
    def __init__(self, possible_values: typing.Iterable[typing.Any]) -> None:
        self.possible_values = list(possible_values)
        listed = " / ".join(map(str, self.possible_values))
        super().__init__({"ru": f"одно из: {listed}", "en": f"one of: {listed}"})

    def validate(self, value: typing.Any) -> typing.Any:
        if value in self.possible_values:
            return value

        for candidate in self.possible_values:
            if str(candidate) == str(value):
                return candidate

        raise ValidationError(f"«{value}» не входит в список допустимых значений")


class MultiChoice(Validator):
    def __init__(self, possible_values: typing.Iterable[typing.Any]) -> None:
        self.choice = Choice(possible_values)
        super().__init__(
            {
                "ru": f"набор значений из: {self.choice.doc['ru']}",
                "en": f"multiple of: {self.choice.doc['en']}",
            }
        )

    def validate(self, value: typing.Any) -> list[typing.Any]:
        if isinstance(value, str):
            value = [item.strip() for item in value.split(",") if item.strip()]

        return [self.choice.validate(item) for item in value]


class Series(Validator):
    """Список значений: принимает как список, так и строку через запятую."""

    def __init__(
        self,
        validator: Validator | None = None,
        *,
        min_len: int = 0,
        max_len: int = 0,
        fixed_len: int = 0,
    ) -> None:
        self.validator = validator
        self.min_len = min_len
        self.max_len = max_len
        self.fixed_len = fixed_len

        inner = f" из «{validator.doc['ru']}»" if validator else ""
        super().__init__({"ru": f"список{inner}", "en": f"series{inner}"})

    def validate(self, value: typing.Any) -> list[typing.Any]:
        if isinstance(value, str):
            value = [item.strip() for item in value.split(",") if item.strip()]

        if not isinstance(value, (list, tuple, set)):
            value = [value]

        value = list(value)

        if self.fixed_len and len(value) != self.fixed_len:
            raise ValidationError(f"В списке должно быть ровно {self.fixed_len} элементов")

        if self.min_len and len(value) < self.min_len:
            raise ValidationError(f"В списке меньше {self.min_len} элементов")

        if self.max_len and len(value) > self.max_len:
            raise ValidationError(f"В списке больше {self.max_len} элементов")

        return [self.validator.validate(item) for item in value] if self.validator else value


class Link(Validator):
    def __init__(self) -> None:
        super().__init__({"ru": "ссылка http(s)://", "en": "http(s) link"})

    def validate(self, value: typing.Any) -> str:
        value = str(value).strip()
        parsed = urlparse(value)

        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValidationError(f"«{value}» не похоже на ссылку")

        return value


class TelegramID(Validator):
    def __init__(self) -> None:
        super().__init__({"ru": "ID пользователя или чата", "en": "telegram id"})

    def validate(self, value: typing.Any) -> int:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            raise ValidationError(f"«{value}» — это не Telegram ID") from None


class Emoji(Validator):
    def __init__(self, *, quantity: int = 0) -> None:
        self.quantity = quantity
        super().__init__({"ru": "эмодзи", "en": "emoji"})

    def validate(self, value: typing.Any) -> str:
        value = str(value).strip()

        if not value:
            raise ValidationError("Нужен хотя бы один эмодзи")

        if self.quantity and len(value) != self.quantity:
            raise ValidationError(f"Ожидаю ровно {self.quantity} эмодзи")

        return value


class Hidden(Validator):
    """Обёртка для секретов: значение не показывается в редакторе конфига."""

    def __init__(self, validator: Validator | None = None) -> None:
        self.validator = validator or Validator()
        super().__init__({"ru": "скрытое значение", "en": "hidden value"})

    def validate(self, value: typing.Any) -> typing.Any:
        return self.validator.validate(value)


class NoneType(Validator):
    def __init__(self) -> None:
        super().__init__({"ru": "пусто", "en": "none"})

    def validate(self, value: typing.Any) -> None:
        if value in (None, "", "None", "null"):
            return None

        raise ValidationError("Здесь должно быть пусто")


class Union(Validator):
    """Подходит, если проходит хотя бы один из вложенных валидаторов."""

    def __init__(self, *validators: Validator) -> None:
        self.validators = validators
        listed = " или ".join(v.doc["ru"] for v in validators)
        super().__init__({"ru": listed, "en": " or ".join(v.doc["en"] for v in validators)})

    def validate(self, value: typing.Any) -> typing.Any:
        for validator in self.validators:
            try:
                return validator.validate(value)
            except ValidationError:
                continue

        raise ValidationError(f"«{value}» не подходит ни под один допустимый формат")
