import pytest

from project.sample import BankAccount


def test_account_initialization():
    account = BankAccount("Alice", 100.0)
    assert account.owner == "Alice"
    assert account.balance == 100.0


def test_deposit_increases_balance():
    account = BankAccount("Bob", 50.0)
    account.deposit(25.0)
    assert account.balance == 75.0


def test_withdraw_insufficient_funds_raises_error():
    account = BankAccount("Charlie", 20.0)
    # This verifies that pytest correctly catches the expected ValueError
    with pytest.raises(ValueError, match="Insufficient funds available."):
        account.withdraw(50.0)
