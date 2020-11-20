import os

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash
import datetime

from helpers import apology, login_required, lookup, usd, vetPassword

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    rows = db.execute("SELECT symbol, shares FROM portfolio WHERE user_id = :user_id;", user_id = session["user_id"])
    totalValue = 0
    for row in rows:
        symbol = row["symbol"]
        quote = lookup(symbol)
        name = quote["name"]
        price = quote["price"]
        #row["symbol"] = symbol.upper() #update the database with capitalized symbol for consistent formating?
        total = float(quote["price"]) * float(row["shares"])
        totalValue += total
        row["name"] = name
        row["total"] = usd(total)
        row["price"] = usd(price)
    userCash = db.execute("SELECT cash FROM users WHERE id = :user_id;", user_id = session["user_id"])
    totalValue = usd(totalValue + userCash[0]["cash"])
    cash = usd(userCash[0]["cash"])
    return render_template("index.html", message = session["message"], rows = rows, cash = cash, totalValue = totalValue)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    if request.method == "POST":
        now = datetime.datetime.now()
        date = now.strftime("%Y-%m-%d")
        time = now.strftime("%H:%M:%S")
        symbol = request.form.get("symbol")
        if not symbol:
            return apology("must enter symbol", 403)
        shares = request.form.get("shares")
        if not shares:
            return apology("must enter number of shares", 403)
        quoted = lookup(symbol)
        price = float(shares) * quoted["price"]
        symbol = quoted["symbol"]
        userCash = db.execute("SELECT cash FROM users WHERE id = :user_id;", user_id = session["user_id"]) # consider storing in session instead
        if quoted == None:
            return apology("symbol not recognized", 403)
        elif price > userCash[0]["cash"]: # see if user can afford stock
           return apology("you do not have enough cash to complete this purchase")
        else: # purchase stock for user
            # modify user's cash in users table
            db.execute("UPDATE users SET cash = :cash WHERE id = :user_id;", cash = userCash[0]["cash"] - price, user_id = session["user_id"])
            # create or modfy user's stock ownership in portfolio table
            db.execute("INSERT INTO portfolio (user_id, symbol, shares) VALUES (:user_id, :symbol, :shares);", user_id = session["user_id"], symbol = symbol, shares = shares)
            # create transaction record
            db.execute("INSERT INTO transactions (user_id, symbol, shares, shareprice, totalprice, date, time) VALUES (:user_id, :symbol, :shares, :shareprice, :totalprice, :date, :time);", user_id = session["user_id"], symbol = symbol, shares = shares, shareprice = quoted["price"], totalprice = price, date = date, time = time)

            message = "You bought " + shares + " shares of " + symbol + "!"
            session["message"] = message

            return redirect("/")
    else:
        return render_template("buy.html")

@app.route("/history")
@login_required
def history():
    session["message"] = "Here is your purchase history!"
    rows = db.execute("SELECT symbol, shares, shareprice, totalprice, date, time FROM transactions WHERE user_id = :user_id;", user_id = session["user_id"]);
    for row in rows:
        symbol = row["symbol"]
        quoted = lookup(symbol)
        name = quoted["name"]
        row["name"] = name
        row["shareprice"] = usd(row["shareprice"])
        row["totalprice"] = usd(row["totalprice"])
        if row["shares"] > 0:
            row["transaction"] = "Purchase"
        else:
            row["transaction"] = "Sale"
    return render_template("history.html", rows = rows, message = session["message"])


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Remember username of user that has logged in
        session["username"] = rows[0]["username"]

        session["message"] = "Welcome back!"

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    if request.method == "POST":
        symbol = request.form.get("symbol")
        quoted = lookup(symbol)
        if quoted == None:
            return apology("symbol not recognized", 403)
        else:
            return render_template("quoted.html", name = quoted["name"], symbol = quoted["symbol"], price = usd(quoted["price"]))
    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":

        # Store variables for local use
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")
        passwordInsecure = vetPassword(password, confirmation)

        # Query database to see if username already exists
        usernameExists = db.execute("SELECT username FROM users WHERE username = :username",
                          username=username)

        # Ensure username was submitted
        if not username:
            return apology("must provide username", 403)

        # Query database to see if username already exists
        elif usernameExists:
            return apology("username already exists", 403)

        elif passwordInsecure:
            return apology(passwordInsecure, 403)

        else:
            # Add user to database
            rows = db.execute("INSERT INTO users (username, hash, cash) VALUES (:username, :hash, :cash);",
                              username=username, hash=generate_password_hash(password), cash=10000)

            session["message"] = "Registered!"

            # Redirect user to home page
            return redirect("/login")


    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    if request.method == "POST":
        now = datetime.datetime.now()
        date = now.strftime("%Y-%m-%d")
        time = now.strftime("%H:%M:%S")
        symbol = request.form.get("symbol")
        if symbol == "Symbol":
            return apology("must select symbol", 403)
        shares = int(request.form.get("shares"))
        if not shares:
            return apology("must enter number of shares", 403)
        quoted = lookup(symbol)
        #symbol = quoted["symbol"]

        rows = db.execute("SELECT symbol, shares FROM portfolio WHERE user_id = :user_id AND symbol = :symbol;", user_id = session["user_id"], symbol = symbol)
        sharesowned = rows[0]["shares"]

        if shares > sharesowned:
            return apology("You are attempting to sell more shares than you own.", 403)
        #update portfolio
        if shares == sharesowned:
            db.execute("DELETE FROM portfolio WHERE user_id = :user_id AND symbol = :symbol;", user_id = session["user_id"], symbol = symbol)
        else:
            db.execute("UPDATE portfolio SET shares = :sharesUpdate WHERE user_id = :user_id AND symbol = :symbol;", sharesUpdate = sharesowned - shares,user_id = session["user_id"], symbol = symbol)
        #update users
        price = float(shares) * quoted["price"]
        userCash = db.execute("SELECT cash FROM users WHERE id = :user_id;", user_id = session["user_id"]) # consider storing in session instead

        db.execute("UPDATE users SET cash = :cash WHERE id = :user_id;", cash = userCash[0]["cash"] + price, user_id = session["user_id"])
        #update transaction history
        db.execute("INSERT INTO transactions (user_id, symbol, shares, shareprice, totalprice, date, time) VALUES (:user_id, :symbol, :shares, :shareprice, :totalprice, :date, :time);", user_id = session["user_id"], symbol = symbol, shares = -shares, shareprice = quoted["price"], totalprice = -price, date = date, time = time)

        message = "You just sold " + str(shares) + " shares of " + symbol + "!"
        session["message"] = message

        return redirect("/")
    else:
        rows = db.execute("SELECT * FROM portfolio WHERE user_id = :user_id;", user_id = session["user_id"])
        for row in rows:
            symbol = row["symbol"]
            #row["symbol"] = symbol.upper()
        return render_template("sell.html", rows=rows)

@app.route("/changepassword", methods=["GET", "POST"])
def changepassword():
    if request.method == "POST":

        # Store variables for local use
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")
        passwordInsecure = vetPassword(password, confirmation)

        if passwordInsecure:
            return apology(passwordInsecure, 403)

        else:
            # Add user to database
            rows = db.execute("UPDATE users SET hash = :hash WHERE id = :user_id;", hash=generate_password_hash(password), user_id = session["user_id"])

            session["message"] = "Your password has been changed successfully!"

            # Redirect user to home page
            return redirect("/")


    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("changepassword.html")


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
