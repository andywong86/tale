class BankAccount:
    """A simple class representing a bank account with deposit and withdrawal features."""

    def __init__(self, owner: str, initial_balance: float = 0.0) -> None:
        self.owner: str = owner
        # A leading underscore signals this attribute is "private" / internal
        self._balance: float = initial_balance

    @property
    def balance(self) -> float:
        """Getter for the balance attribute (read-only from outside)."""
        return self._balance

    def deposit(self, amount: float) -> None:
        """Adds funds to the account."""
        if amount <= 0:
            raise ValueError("Deposit amount must be positive.")
        self._balance += amount

    def withdraw(self, amount: float) -> None:
        """Deducts funds if sufficient balance exists."""
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive.")
        if amount > self._balance:
            raise ValueError("Insufficient funds available.")
        self._balance -= amount

    def __repr__(self) -> str:
        """Returns a string representation of the object for debugging."""
        return f"BankAccount(owner='{self.owner}', balance={self._balance})"
