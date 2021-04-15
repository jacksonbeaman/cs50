import os
import requests
import urllib.parse
import re

from flask import redirect, render_template, request, session
from functools import wraps


def apology(message, code=400):
    """Render message as an apology to user."""
    def escape(s):
        """
        Escape special characters.

        https://github.com/jacebrowning/memegen#special-characters
        """
        for old, new in [("-", "--"), (" ", "-"), ("_", "__"), ("?", "~q"),
                         ("%", "~p"), ("#", "~h"), ("/", "~s"), ("\"", "''")]:
            s = s.replace(old, new)
        return s
    return render_template("apology.html", top=code, bottom=escape(message)), code


def login_required(f):
    """
    Decorate routes to require login.

    http://flask.pocoo.org/docs/1.0/patterns/viewdecorators/
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function


def lookup(symbol):
    """Look up quote for symbol."""

    # Contact API
    try:
        api_key = os.environ.get("API_KEY")
        response = requests.get(f"https://cloud.iexapis.com/stable/stock/{urllib.parse.quote_plus(symbol)}/quote?token={api_key}")
        response.raise_for_status()
    except requests.RequestException:
        return None

    # Parse response
    try:
        quote = response.json()
        return {
            "name": quote["companyName"],
            "price": float(quote["latestPrice"]),
            "symbol": quote["symbol"]
        }
    except (KeyError, TypeError, ValueError):
        return None


def usd(value):
    """Format value as USD."""
    return f"${value:,.2f}"

def vetPassword(password, confirmation):
    if not password:
        return "must provide password"
    elif not confirmation:
        return "must confirm password"
    elif len(password) != len(confirmation) or password != confirmation:
        return "passwords do not match"
    elif len(password) < 8:
        return "Your password must be at least 8 characters long"
    elif not re.search("[a-z]", password):
        return "Your password must contain at least one lowercase alphabetical character"
    elif not re.search("[A-Z]", password):
        return "Your password must contain at least one uppercase alphabetical character"
    elif not re.search("[0-9]", password): #could use "/d"
        return "Your password must contain at least one number"
    elif not re.search("\W|_", password):
        return "Your password must contain at least one special character"
    else:
        return None