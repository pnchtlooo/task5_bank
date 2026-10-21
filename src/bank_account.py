import csv
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from itertools import count
from uuid import uuid4


class BankAccount:
    """Банковский счёт с историей операций."""

    _next_account_number = count(1000)

    def __init__(self, owner: str, balance = 0):
        if not isinstance(owner, str):
            raise TypeError("Имя владельца должно быть строкой")
        name_pattern = (
            r"^[А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+$"
            r"|^[A-Z][a-z]+ [A-Z][a-z]+$"
        )
        if not re.fullmatch(name_pattern, owner.strip()):
            raise ValueError(
                "Введите имя и фамилию с заглавной буквы "
                "(кириллица или латиница)"
            )

        self.owner = owner.strip()
        self.account_number = f"ACC-{next(self._next_account_number)}"
        self.account_type = "base"

        self._balance = self._to_decimal(balance, allow_zero=True)
        self._history = []

    @staticmethod
    def _to_decimal(value, allow_zero=False):
        if isinstance(value, bool):
            raise TypeError("Сумма должна быть числом")

        if not isinstance(value, (int, float, str, Decimal)):
            raise TypeError("Сумма должна быть числом")

        try:
            amount = Decimal(str(value))
        except InvalidOperation:
            raise ValueError("Некорректная сумма")

        if not amount.is_finite():
            raise ValueError("Сумма должна быть конечным числом")

        if amount < 0 or (not allow_zero and amount == 0):
            if allow_zero:
                raise ValueError("Баланс не может быть отрицательным")
            raise ValueError("Сумма операции должна быть положительной")

        return amount

    @property
    def balance(self):
        return self._balance

    def get_balance(self):
        return self._balance

    def get_history(self):
        return [record.copy() for record in self._history]

    def _record(self, operation, amount, status, transfer_id=None):
        self._history.append({
            "operation": operation,
            "amount": amount,
            "date": datetime.now(),
            "balance_after": self._balance,
            "status": status,
            "transfer_id": transfer_id,
        })

    def deposit(self, amount):
        amount = self._to_decimal(amount)
        self._balance += amount
        self._record("deposit", amount, "success")
        return True

    def _can_withdraw(self, amount):
        """Проверяет возможность снятия без изменения баланса."""
        return amount <= self._balance

    def withdraw(self, amount):
        amount = self._to_decimal(amount)

        if not self._can_withdraw(amount):
            self._record("withdraw", amount, "fail")
            return False

        self._balance -= amount
        self._record("withdraw", amount, "success")
        return True

    def add_interest(self, rate):
        raise NotImplementedError(
            "Начисление процентов доступно только для сберегательного счёта"
        )

    def get_large_operations(self, threshold, n):
        """Последние n успешных операций не меньше порога."""
        threshold = self._to_decimal(threshold, allow_zero=True)

        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise ValueError("Количество операций n должно быть целым числом >= 0")

        operations = [
            record.copy()
            for record in self._history
            if record["status"] == "success"
               and record["amount"] >= threshold
        ]

        return operations[-n:] if n else []

    def display_history(self):
        if not self._history:
            print("История операций пуста.")
            return

        print(f"История счёта {self.account_number} ({self.account_type})")
        print("-" * 90)

        for record in self._history:
            date = record["date"].strftime("%d.%m.%Y %H:%M:%S")
            transfer = record["transfer_id"] or "-"
            print(
                f'{date} | {record["operation"]:<16} | '
                f'{record["amount"]:>10.2f} | '
                f'{record["balance_after"]:>10.2f} | '
                f'{record["status"]:<7} | {transfer}'
            )

    def transfer_to(self, recipient, amount):
        """Перевод с записью связанных операций на обоих счетах."""
        if not isinstance(recipient, BankAccount):
            raise TypeError("Получатель должен быть банковским счётом")

        if recipient is self:
            raise ValueError("Нельзя переводить деньги на тот же счёт")

        amount = self._to_decimal(amount)
        transfer_id = str(uuid4())

        # Проверяем ограничения отправителя до изменения обоих балансов.
        if not self._can_withdraw(amount):
            self._record(
                "transfer_out", amount, "fail", transfer_id
            )
            recipient._record(
                "transfer_in", amount, "fail", transfer_id
            )
            return False

        self._balance -= amount
        recipient._balance += amount

        self._record("transfer_out", amount, "success", transfer_id)
        recipient._record("transfer_in", amount, "success", transfer_id)
        return True

    def load_history_csv(self, file_path):
        """Загружает валидные операции этого счёта из CSV.

        Возвращает отчёт с количеством принятых и отклонённых строк.
        """
        allowed_operations = {
            "checking": {"deposit", "withdraw"},
            "savings": {"deposit", "withdraw", "interest"},
        }
        allowed_statuses = {"success", "fail"}

        if self.account_type not in allowed_operations:
            raise ValueError(
                f"Неизвестный тип счёта: {self.account_type}"
            )

        report = {
            "accepted": 0,
            "rejected": 0,
            "errors": [],
        }

        seen_rows = set()

        def parse_date(value):
            formats = (
                "%Y-%m-%d %H:%M:%S",
                "%d/%m/%Y %H:%M",
            )

            for date_format in formats:
                try:
                    return datetime.strptime(value.strip(), date_format)
                except ValueError:
                    continue

            raise ValueError("некорректная дата")

        with open(file_path, "r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)

            required_columns = {
                "account_number",
                "account_type",
                "date",
                "operation",
                "amount",
                "balance_after",
                "status",
            }

            if not reader.fieldnames or not required_columns.issubset(
                    reader.fieldnames
            ):
                raise ValueError("В CSV отсутствуют необходимые столбцы")

            for row_number, row in enumerate(reader, start=2):
                # Файл общий: чужие счета не загружаем и не считаем ошибками.
                if row["account_number"].strip() != self.account_number:
                    continue

                if row["account_type"].strip() != self.account_type:
                    report["rejected"] += 1
                    report["errors"].append({
                        "row": row_number,
                        "reason": "Тип счёта не совпадает с типом объекта",
                    })
                    continue

                # Отсекаем точные дубликаты строк этого счёта.
                signature = tuple(
                    (key, row.get(key, "").strip())
                    for key in reader.fieldnames
                )

                if signature in seen_rows:
                    report["rejected"] += 1
                    report["errors"].append({
                        "row": row_number,
                        "reason": "Повторяющаяся строка",
                    })
                    continue

                seen_rows.add(signature)

                try:
                    operation = row["operation"].strip()
                    status = row["status"].strip()
                    operation_date = parse_date(row["date"])

                    if operation not in allowed_operations[self.account_type]:
                        raise ValueError(
                            f"Недопустимая операция: {operation!r}"
                        )

                    if status not in allowed_statuses:
                        raise ValueError(
                            f"Некорректный статус: {status!r}"
                        )

                    if not row["amount"].strip():
                        raise ValueError("Пустая сумма")

                    amount = self._to_decimal(row["amount"])

                    # Проверяем возможность операции до изменения баланса.
                    if status == "success":
                        if operation == "withdraw":
                            if not self._can_withdraw(amount):
                                raise ValueError(
                                    "Недостаточно средств или превышен лимит снятия"
                                )

                        # Применяем только успешные операции.
                        if operation == "deposit":
                            self._balance += amount
                        elif operation == "withdraw":
                            self._balance -= amount
                        elif operation == "interest":
                            self._balance += amount

                    # История хранит дату из исходного файла.
                    self._history.append({
                        "operation": operation,
                        "amount": amount,
                        "date": operation_date,
                        "balance_after": self._balance,
                        "status": status,
                        "transfer_id": None,
                    })

                    report["accepted"] += 1

                except (ValueError, TypeError) as error:
                    report["rejected"] += 1
                    report["errors"].append({
                        "row": row_number,
                        "reason": str(error),
                    })

        return report

class CheckingAccount(BankAccount):
    """Расчётный счёт без специальных ограничений на снятие."""

    def __init__(self, owner, balance=0):
        super().__init__(owner, balance)
        self.account_type = "checking"


class SavingsAccount(BankAccount):
    """Сберегательный счёт с процентами и ограничением снятия."""

    def __init__(self, owner, balance=0):
        super().__init__(owner, balance)
        self.account_type = "savings"

    def _can_withdraw(self, amount):
        return (
            amount <= self._balance
            and amount <= self._balance * Decimal("0.5")
        )

    def add_interest(self, rate):
        rate = self._to_decimal(rate, allow_zero=True)

        if rate > 100:
            raise ValueError("Ставка не может превышать 100%")

        interest = (
            self._balance * rate / Decimal("100")
        ).quantize(Decimal("0.01"))

        if interest > 0:
            self._balance += interest
            self._record("interest", interest, "success")

        return interest







