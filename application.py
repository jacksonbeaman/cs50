import os
import pylibmc
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash
import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import JSON

from helpers import apology, login_required, lookup, usd, vetPassword

# Configure application and database engine
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

#Configure session to use filesystem (instead of signed cookies)
#app.config["SESSION_FILE_DIR"] = mkdtemp()
#app.config["SESSION_PERMANENT"] = False
#app.config["SESSION_TYPE"] = "filesystem"
#Session(app)

# Configure SQLAlchemy to use postgreSQL database
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Configure session to use memcache
cache_servers = os.environ.get('MEMCACHIER_SERVERS').split(',')
cache_user = os.environ.get('MEMCACHIER_USERNAME')
cache_pass = os.environ.get('MEMCACHIER_PASSWORD')

app.config.from_mapping(
    SESSION_TYPE = 'memcached',
    SESSION_MEMCACHED =
        pylibmc.Client(cache_servers, binary=True,
                       username=cache_user, password=cache_pass,
                       behaviors={
                            # Faster IO
                            'tcp_nodelay': True,
                            # Keep connection alive
                            'tcp_keepalive': True,
                            # Timeout for set/get requests
                            'connect_timeout': 2000, # ms
                            'send_timeout': 750 * 1000, # us
                            'receive_timeout': 750 * 1000, # us
                            '_poll_timeout': 2000, # ms
                            # Better failover
                            'ketama': True,
                            'remove_failed': 1,
                            'retry_timeout': 2,
                            'dead_timeout': 30,
                       })
)

Session(app)

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String, nullable=False)
    hash = db.Column(db.String, nullable=False)
    cash = db.Column(db.Numeric, nullable=False)

class Position(db.Model):
    __tablename__ = "positions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    symbol = db.Column(db.String, nullable=False)
    shares = db.Column(db.Integer, nullable=False)

class Transaction(db.Model):
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    symbol = db.Column(db.String, nullable=False)
    shares = db.Column(db.Integer, nullable=False)
    shareprice = db.Column(db.Numeric, nullable=False)
    totalprice = db.Column(db.Numeric, nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)


# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    session["message"] = "Here is your portfolio!"
    positions = Position.query.filter_by(user_id = session["user_id"]).all()
    # initialize list of dictionaries for rendering
    rows = [dict() for x in range(len(positions))]
    totalValue = 0
    for row, position in zip(rows, positions):
        symbol = position.symbol
        quote = lookup(symbol)
        name = quote["name"]
        price = quote["price"]
        shares = position.shares
        total = float(quote["price"]) * float(shares)
        totalValue += total
        # add data to rows from rendering
        row["symbol"] = symbol
        row["name"] = name
        row["shares"] = shares
        row["total"] = usd(total)
        row["price"] = usd(price)

    user = User.query.filter_by(id = session["user_id"]).first() # returns a single user object
    totalValue = usd(totalValue + float(user.cash))
    cash = usd(user.cash)
    rows.sort(key = lambda i: i['symbol'])
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
        # remove leading and trailing whitespaces from user input - iOS mobile issue
        symbol = symbol.strip()
        quoted = lookup(symbol)
        shareprice = quoted["price"]
        price = round(float(shares) * shareprice, 2)
        # redefine / reassign symbol to that which was returned from API - instead of what user typed in
        symbol = quoted["symbol"]
        user = User.query.filter_by(id = session["user_id"]).first()
        if quoted == None:
            return apology("symbol not recognized", 403)
        elif price > float(user.cash): # see if user can afford stock
           return apology("you do not have enough cash to complete this purchase")
        else: # purchase stock for user
            # modify user's cash in users table
            user.cash = float(user.cash) - price
            # create or modfy user's stock ownership in positions table
            # check if user already owns shares of this stock
            position = Position.query.filter_by(user_id = session["user_id"], symbol = symbol).first()
            # if user does not already own stock, create new row for new stock
            if not position:
                # Insert new position
                new_position = Position(user_id = session["user_id"], symbol = symbol, shares = shares)
                db.session.add(new_position)
            # else update row with new share total if user already owns stock    
            else:
                new_shares_total = int(position.shares) + int(shares)          
                position.shares = new_shares_total
            # create transaction record
            new_transaction = Transaction(user_id = session["user_id"], symbol = symbol, shares = shares, shareprice = shareprice, totalprice = -price, date = date, time = time)
            db.session.add(new_transaction)
            db.session.commit()  

            message = "You bought " + shares + " shares of " + symbol + "!"
            session["message"] = message

            return redirect("/")
    else:
        return render_template("buy.html")

@app.route("/history")
@login_required
def history():
    session["message"] = "Here is your purchase history!"
    transactions = Transaction.query.filter_by(user_id = session["user_id"]).all()
    # initialize list of dictionaries for rendering
    rows = [dict() for x in range(len(transactions))]
    for row, transaction in zip(rows, transactions):
        symbol = transaction.symbol
        quoted = lookup(symbol)
        name = quoted["name"]
        # add data to rows from rendering
        row["name"] = name
        row["symbol"] = symbol
        row["shares"] = transaction.shares
        row["shareprice"] = usd(transaction.shareprice)
        if transaction.totalprice > 0:
            row["totalprice"] = "+" + usd(transaction.totalprice)
        else:
            row["totalprice"] = "-" + usd(-transaction.totalprice)
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
        # .first() method just returns a single object, not a list of objects / list of rows
        user = User.query.filter_by(username = request.form.get("username")).first()
        
        # Ensure username exists and password is correct
        if not user or not check_password_hash(user.hash, request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = user.id

        # Remember username of user that has logged in
        session["username"] = user.username

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
        # remove leading and trailing whitespaces from user input - iOS mobile issue
        symbol = symbol.strip()
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
        #elif db.execute("SELECT username FROM users WHERE username = :username", {"username": username}).rowcount == 1:
        elif len(User.query.filter_by(username = username).all()) == 1:
            users = User.query.filter_by(username = username).all()
            print (users)
            return apology("username already exists", 403)

        elif passwordInsecure:
            return apology(passwordInsecure, 403)

        else:
            # Add user to database
            # db.execute("INSERT INTO users (username, hash, cash) VALUES (:username, :hash, :cash);",
            #                  {"username": username, "hash": generate_password_hash(password), "cash": 10000})
            new_user = User(username = username, hash = generate_password_hash(password), cash = 10000)
            db.session.add(new_user)
            print(f"New user added: {new_user.username} with ${new_user.cash}")

            db.session.commit()                  

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

        position = Position.query.filter_by(user_id = session["user_id"], symbol = symbol).first()
        shares_owned = position.shares

        if shares > shares_owned:
            return apology("You are attempting to sell more shares than you own.", 403)
        #update positions table
        if shares == shares_owned:
            db.session.delete(position)
        else:
            position.shares = shares_owned - shares

        #update users table
        shareprice = quoted["price"]
        saleprice = float(shares) * shareprice
        user = User.query.filter_by(id = session["user_id"]).first()
        user.cash = round(float(user.cash) + saleprice, 2)

        #update transaction history
        new_transaction = Transaction(user_id = session["user_id"], symbol = symbol, shares = -shares, shareprice = shareprice, totalprice = saleprice, date = date, time = time)
        db.session.add(new_transaction)
        
        db.session.commit()

        message = "You just sold " + str(shares) + " shares of " + symbol + "!"
        session["message"] = message

        return redirect("/")
    else:
        positions = Position.query.filter_by(user_id = session["user_id"]).all()
        # initialize list of dictionaries for rendering
        rows = [dict() for x in range(len(positions))]
        for row, position in zip(rows, positions):
            # add data to rows from rendering
            row["symbol"] = position.symbol
            row["shares"] = position.shares
        rows.sort(key = lambda i: i['symbol'])
        return render_template("sell.html", rows=rows)

@app.route("/changepassword", methods=["GET", "POST"])
@login_required
def changepassword():
    if request.method == "POST":
        # Store variables for local use
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")
        passwordInsecure = vetPassword(password, confirmation)

        if passwordInsecure:
            return apology(passwordInsecure, 403)

        else:
            # Update user hash
            user = User.query.filter_by(id = session["user_id"]).first()
            user.hash = generate_password_hash(password)
            db.session.commit()
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
