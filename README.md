# Bank Statement Analysis Dashboard

A dynamic, web-based financial analysis tool designed to process bank statement CSVs, categorize transactions, and visualize expenses through an interactive dashboard.

## 🌟 Features

-   **Interactive Dashboard**: Visualize your financial data with KPI cards, expense distribution charts, and detailed breakdown tables.
-   **Dynamic Categorization**:
    -   Rules are defined in `config.json` and can be edited via the web interface.
    -   Automatically detects Salary, Director Remuneration, Business Travel, Recurring Services, etc.
-   **Admin Interface**:
    -   **File Upload**: Upload new bank statement CSVs directly from the browser to update the dashboard instantly.
    -   **Configuration Management**: Add/Remove Directors, Employees, and Vendor/Party Mappings without touching code.
-   **Financial Year Detection**: Automatically detects and displays the Financial Year (e.g., FY 2025-26) based on transaction dates.
-   **Smart Grouping**: Automatically consolidates "ATM / Debit Card Charges" and cleans up vendor names (e.g., merging various "FlixBus" entries).

## 🛠️ Technology Stack

-   **Backend**: Python (Flask, Pandas)
-   **Frontend**: HTML5, Tailwind CSS (CDN), Chart.js
-   **Data**: CSV processing, JSON configuration

## 🚀 Getting Started

### Prerequisites

-   Python 3.x
-   pip (Python package manager)

### Installation

1.  **Clone/Navigate** to the project directory:
    ```bash
    cd /path/to/Bank_statement
    ```

2.  **Install Dependencies**:
    You need `flask`, `pandas`, and `openpyxl` (for Excel support if needed, though strictly CSV is used currently).
    ```bash
    pip install flask pandas openpyxl
    ```

### Running the Application

1.  **Start the Server**:
    By default, it runs on port 5000, or you can specify a port.
    ```bash
    # Run on default port 5000
    python app.py
    
    # OR Run on port 8080 (Recommended)
    export PORT=8080 && python app.py
    ```

2.  **Access the Dashboard**:
    Open your browser and navigate to:
    [http://localhost:8080](http://localhost:8080) (or whichever port you used).

3.  **Login**:
    To access the **Admin** features (Upload, Config), use the top-right button.
    -   **Username**: `admin`
    -   **Password**: `admin`

## 📂 Project Structure

-   **`app.py`**: Main Flask application handling routes, logic, and data analysis.
-   **`config.json`**: Stores dynamic rules for Directors, Employees, and Party Mappings.
-   **`templates/`**:
    -   `dashboard.html`: The main analytics view.
    -   `admin.html`: Configuration & Upload interface.
    -   `login.html`: Authentication page.
-   **`files/`**:
    -   `easy_withdrawl.csv`: The current active bank statement file being analyzed.
-   **`main.py`**: (Legacy) Standalone CLI script for analysis.

## 📝 Usage Guide

1.  **Analyze New Data**: Go to the Admin panel -> "Data Source" -> Upload a new `.csv` bank statement. The dashboard will update immediately.
2.  **Refine Categories**: If you see "Other / Uncategorized" transactions:
    -   Go to Admin.
    -   Add a **Party Mapping** (e.g., "AMZN" -> "Amazon").
    -   The dashboard will re-process and group those transactions correctly.

## 🔒 Security Note
The default credentials are simpler for local usage. For production deployment, please change the `secret_key` in `app.py` and update the authentication logic.
