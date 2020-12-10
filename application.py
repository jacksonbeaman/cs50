import os

#from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash
import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from helpers import apology, login_required, lookup, usd, vetPassword

# Configure application and database engine
app = Flask(__name__)
engine = create_engine(os.getenv("DATABASE_URL"))
db = scoped_session(sessionmaker(bind=engine))

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

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    session["message"] = "Here is your portfolio!"
    # SQLAlchemy returns a list of Tuples
    portfolio = db.execute("SELECT symbol, shares FROM portfolio WHERE user_id = :user_id;", {"user_id": session["user_id"]}).fetchall()
    print (portfolio)
    print (len(portfolio))
    # initialize list of dictionaries - easier to use than tuple returned by the databas engine
    rows = [dict() for x in range(len(portfolio))]
    print (rows)
    totalValue = 0
    for row, portfolio_stock in zip(rows, portfolio):
        # tuple values are indexed by integers
        symbol = portfolio_stock.symbol # using sqlite: row["symbol"]; portfolio_stock[0] also works with postgreSQL - just accessing a tuple value
        quote = lookup(symbol)
        name = quote["name"]
        price = quote["price"]
        shares = portfolio_stock.shares # using sqlite: ...float(row["shares"]); portfolio_stock[1] also works with postgreSQL - just accessing a tuple value
        #row["symbol"] = symbol.upper() #update the database with capitalized symbol for consistent formating?
        total = float(quote["price"]) * float(shares) # using sqlite: ...float(row["shares"])
        totalValue += total
        # add data to rows from rendering
        row["symbol"] = symbol
        row["name"] = name
        row["shares"] = shares
        row["total"] = usd(total)
        row["price"] = usd(price)
    userCash = db.execute("SELECT cash FROM users WHERE id = :user_id;", {"user_id": session["user_id"]}).fetchone()
    print (userCash)
    print (userCash[0])
    print (userCash.cash)
    totalValue = usd(totalValue + float(userCash.cash)) # using sqlite: userCash[0]["cash"])
    cash = usd(userCash.cash) # using sqlite: userCash[0]["cash"])
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
        # redefine / reassign symbol to that which was returned from API - instead of what user typed in
        symbol = quoted["symbol"]
        userCash = db.execute("SELECT cash FROM users WHERE id = :user_id;", {"user_id": session["user_id"]}).fetchone() # consider storing in session instead
        if quoted == None:
            return apology("symbol not recognized", 403)
        elif price > float(userCash.cash): # see if user can afford stock
           return apology("you do not have enough cash to complete this purchase")
        else: # purchase stock for user
            # modify user's cash in users table
            db.execute("UPDATE users SET cash = :cash WHERE id = :user_id;", {"cash": float(userCash.cash) - price, "user_id": session["user_id"]})
            # create or modfy user's stock ownership in portfolio table
            # check if user already owns shares of this stock
            sharesOwned = db.execute("SELECT shares FROM portfolio WHERE user_id = :user_id AND symbol = :symbol;", {"user_id": session["user_id"], "symbol": symbol}).fetchone()
            # if user does not already own stock, create new row for new stock
            if not sharesOwned:
                db.execute("INSERT INTO portfolio (user_id, symbol, shares) VALUES (:user_id, :symbol, :shares);", {"user_id": session["user_id"], "symbol": symbol, "shares": shares})
                db.commit()
            # else update row with new share total if user already owns stock    
            else:
                newSharesTotal = int(sharesOwned.shares) + int(shares)  
                db.execute("UPDATE portfolio SET shares = :shares WHERE user_id = :user_id AND symbol = :symbol;", {"shares": newSharesTotal, "user_id": session["user_id"], "symbol": symbol})          
                db.commit()
            # create transaction record
            db.execute("INSERT INTO transactions (user_id, symbol, shares, shareprice, totalprice, date, time) VALUES (:user_id, :symbol, :shares, :shareprice, :totalprice, :date, :time);", {"user_id": session["user_id"], "symbol": symbol, "shares": shares, "shareprice": quoted["price"], "totalprice": price, "date": date, "time": time})
            db.commit()
            message = "You bought " + shares + " shares of " + symbol + "!"
            session["message"] = message

            return redirect("/")
    else:
        return render_template("buy.html")

@app.route("/history")
@login_required
def history():
    session["message"] = "Here is your purchase history!"
    transactions = db.execute("SELECT symbol, shares, shareprice, totalprice, date, time FROM transactions WHERE user_id = :user_id;", {"user_id": session["user_id"]}).fetchall()
    rows = [dict() for x in range(len(transactions))]
    for row, transaction in zip(rows, transactions):
        symbol = transaction.symbol # using sqlite row["symbol"]
        quoted = lookup(symbol)
        name = quoted["name"]
        row["name"] = name
        row["symbol"] = symbol
        row["shares"] = transaction.shares
        row["shareprice"] = usd(transaction.shareprice) # using sqlite usd(row["shareprice"])
        row["totalprice"] = usd(transaction.totalprice)
        row["date"] = transaction.date
        row["time"] = transaction.time
        if transaction.shares > 0:
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
        rows = db.execute("SELECT * FROM users WHERE username = :username", {"username": request.form.get("username")}).fetchall()
        
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

        # Ensure username was submitted
        if not username:
            return apology("must provide username", 403)

        # Query database to see if username already exists
        elif db.execute("SELECT username FROM users WHERE username = :username", {"username": username}).rowcount == 1:
            return apology("username already exists", 403)

        elif passwordInsecure:
            return apology(passwordInsecure, 403)

        else:
            # Add user to database
            db.execute("INSERT INTO users (username, hash, cash) VALUES (:username, :hash, :cash);",
                              {"username": username, "hash": generate_password_hash(password), "cash": 10000})
            db.commit()                  

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

        portfolio = db.execute("SELECT symbol, shares FROM portfolio WHERE user_id = :user_id AND symbol = :symbol;", {"user_id": session["user_id"], "symbol": symbol}).fetchone()
        sharesowned = portfolio.shares

        if shares > sharesowned:
            return apology("You are attempting to sell more shares than you own.", 403)
        #update portfolio
        if shares == sharesowned:
            db.execute("DELETE FROM portfolio WHERE user_id = :user_id AND symbol = :symbol;", {"user_id": session["user_id"], "symbol": symbol})
        else:
            db.execute("UPDATE portfolio SET shares = :sharesUpdate WHERE user_id = :user_id AND symbol = :symbol;", {"sharesUpdate": sharesowned - shares,"user_id": session["user_id"], "symbol": symbol})
        #update users
        price = float(shares) * quoted["price"]
        userCash = db.execute("SELECT cash FROM users WHERE id = :user_id;", {"user_id": session["user_id"]}).fetchone() # consider storing in session instead

        db.execute("UPDATE users SET cash = :cash WHERE id = :user_id;", {"cash": float(userCash.cash) + price, "user_id": session["user_id"]})
        #update transaction history
        db.execute("INSERT INTO transactions (user_id, symbol, shares, shareprice, totalprice, date, time) VALUES (:user_id, :symbol, :shares, :shareprice, :totalprice, :date, :time);", {"user_id": session["user_id"], "symbol": symbol, "shares": -shares, "shareprice": quoted["price"], "totalprice": -price, "date": date, "time": time})

        db.commit()
        message = "You just sold " + str(shares) + " shares of " + symbol + "!"
        session["message"] = message

        return redirect("/")
    else:
        portfolio = db.execute("SELECT symbol, shares FROM portfolio WHERE user_id = :user_id;", {"user_id": session["user_id"]}).fetchall()
        rows = [dict() for x in range(len(portfolio))]
        for row, portfolio_stock in zip(rows, portfolio):
            row["symbol"] = portfolio_stock.symbol
            row["shares"] = portfolio_stock.shares
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
            rows = db.execute("UPDATE users SET hash = :hash WHERE id = :user_id;", {"hash": generate_password_hash(password), "user_id": session["user_id"]})
            db.commit()
            
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
