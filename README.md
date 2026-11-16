# Personal Expense Tracker (Household Ledger)

A fast, lightweight, and dependency-free personal expense management web application. Built with pure Python (using only standard library HTTP and SQLite modules) on the backend and modern vanilla JavaScript with Chart.js on the frontend.

---

## Features

- **Zero External Dependencies**: Runs entirely on the Python standard library—no `pip install` required.
- **Persistent Local Database**: Thread-safe SQLite backend with Write-Ahead Logging (`WAL` mode) and connection pooling timeout protections.
- **Interactive Visualizations**: Real-time spending breakdowns by category and monthly spending trend lines powered by Chart.js.
- **Dynamic Filters**: Filter transactions seamlessly by month and category with persistent dropdown state synchronization.
- **Month-over-Month Analytics**: Dynamic calendar-aware MoM spending change metrics.
- **Export to CSV**: One-click spreadsheet export with CSV formula injection mitigation and UTF-8 BOM encoding.
- **Security & Validation**: Strict input sanitization, RFC 8259-compliant numeric constraints (rejecting `NaN` and `Infinity`), XSS prevention, and calendar date validation.

---

## Project Structure

```text
├── index.html       # Responsive web frontend & interactive dashboard
├── server.py        # Python HTTP server & SQLite REST API
├── .gitignore       # Repository ignore rules
└── README.md        # Project documentation
```

---

## Getting Started

### Prerequisites

- Python 3.8 or higher.

### Running the Application

1. Clone the repository:
   ```bash
   git clone https://github.com/cssarthakjagdale-maker/EXPENSE-TRACKER.git
   cd EXPENSE-TRACKER
   ```

2. Start the local server:
   ```bash
   python server.py
   ```

3. Open your browser and navigate to:
   ```text
   http://localhost:8000
   ```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` or `/index.html` | Serves the frontend single-page application. |
| `GET` | `/api/expenses` | Returns all recorded expenses ordered by date descending. |
| `POST` | `/api/expenses` | Creates a new expense entry (`date`, `category`, `description`, `amount`). |
| `DELETE` | `/api/expenses/:id` | Deletes an expense entry by its unique identifier. |

### Sample POST Request Payload

```json
{
  "date": "2026-11-16",
  "category": "Food",
  "description": "Groceries",
  "amount": 45.50
}
```

---

## Author

- **Sarthak Jagdale**
- **GitHub**: [@cssarthakjagdale-maker](https://github.com/cssarthakjagdale-maker)
- **Email**: [cs.sarthakjagdale@gmail.com](mailto:cs.sarthakjagdale@gmail.com)

---

## License

This project is licensed under the MIT License.
