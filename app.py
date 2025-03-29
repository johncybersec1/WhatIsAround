from flask import Flask, render_template, url_for, jsonify,redirect, flash, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import os
from dotenv import load_dotenv
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

app = Flask(__name__)

load_dotenv()
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DB_URI")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


FOUR_KEY = os.getenv("FOUR_KEY")
EVE_KEY = os.getenv("EVE_KEY")

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

class User(db.Model, UserMixin):
    id= db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique = True, nullable = False)
    f_name = db.Column(db.String(50), nullable = False)
    password = db.Column(db.String(200), nullable = False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route("/register", methods = ["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        fname = request.form["fname"]
        password = request.form["password"]

        if User.query.filter_by(username=username).first():
            flash("Username already exists!", "danger")
            return redirect(url_for("register"))
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(username=username, f_name=fname, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        flash("Account Created! You can login.", "success")
        return redirect(url_for("login"))
    return render_template("signup.html")

@app.route("/login", methods = ["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash("Login successful!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid credentials, please try again.", "danger")

    return render_template("login.html")

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

def get_location():
    response = requests.get("https://ipinfo.io/json")
    data = response.json()
    if "loc" in data:
        lat, lon = map(float, data["loc"].split(","))
        return lat, lon
    return None
def find_restaurants(lat, lon, radius=1000, limit=5):
    url = "https://api.foursquare.com/v3/places/search"
    headers = {
        "Accept": "application/json",
        "Authorization": FOUR_KEY
    }
    params = {
        "query": "restaurant",
        "ll": f"{lat},{lon}",
        "radius": radius,
        "limit": limit
    }
    response = requests.get(url, headers=headers, params=params)
    data = response.json()
    if "results" in data:
        return [{"name": place["name"], "address": place["location"]["formatted_address"]} for place in data["results"]]
    return None
@app.route('/restaurants')
def get_restaurants():
    user_location = get_location()
    if user_location:
        lat, lon = user_location
        print(f"Detected location: {lat}, {lon}")
        restaurants = find_restaurants(lat, lon)
        if restaurants:
            print("\nNearby Restaurants: ")

            return render_template('restaurants.html', restaurants=restaurants)
            
        else:
            return render_template('restaurants.html', erro="Could not locate any restaurants nearby.")
    else:
        return render_template('restaurants.html', error="Could not determine location")

def tocity(lat, lon):
    try:
        if lat and lon:
            geolocator = Nominatim(user_agent="FindMy")
            location = geolocator.reverse((lat, lon), language="en", exactly_one=True)

            if location and "address" in location.raw:
                address = location.raw["address"]
                return address.get("city") or address.get("town") or address.get("village") or address.get("municipality", "Unknown")
    except GeocoderTimedOut:
        return "Location lookup timed out"
    except Exception as e:
        return f"Hard to find City :( "

    return "Unknown"
@app.route("/hotels")
def get_hotel():
    try:
        user_location = get_location()
        if not user_location:
            return render_template("hotels.html", hotels=[], error="Could not determine location")
            
        lat, lon = user_location
        overpass_url = "http://overpass-api.de/api/interpreter"
        overpass_query = f"""
        [out:json];
        node["tourism"="hotel"](around:5000,{lat},{lon});
        out body;
        """

        response = requests.post(overpass_url, data={"data": overpass_query})
        
        if response.status_code == 200:
            data = response.json()
            hotels = data.get("elements", [])
            
            hotel_list = []
            for hotel in hotels:
                name = hotel.get("tags", {}).get("name", "Unnamed Hotel")
                hotel_lat = hotel.get("lat")
                hotel_lon = hotel.get("lon")
                city = tocity(hotel_lat, hotel_lon)
                hotel_list.append({"name": name, "lat": hotel_lat, "lon": hotel_lon, "city":city})

            return render_template("hotels.html", hotels=hotel_list)
        else:
            return render_template("hotels.html", hotels=[], error=f"Error fetching hotels: {response.status_code}")
    except Exception as e:
        return render_template("hotels.html", hotels=[], error=str(e))

def get_events():
    try:
        lat, lon = get_location()
        if not lat or not lon:
            return jsonify({"error": "Could not determine location"}), 400
        
        city = tocity(lat, lon)
        if city == "Unknown":
            return jsonify({"error": "Could not determine city"}), 400

        url = f'https://app.ticketmaster.com/discovery/v2/events.json?city={city}&apikey={EVE_KEY}'
        response = requests.get(url)

        if response.status_code == 200:
            events_data = response.json()
            events = events_data.get('_embedded', {}).get('events', [])
            
            event_list = []
            for event in events:
                name = event.get('name', 'Unknown Event')
                image_url = event['_embedded']['attractions'][0]['images'][0]['url'] if '_embedded' in event and 'images' in event['_embedded']['attractions'][0] else None
                genre = event['_embedded']['attractions'][0]['classifications'][0]['genre']['name'] if '_embedded' in event and 'classifications' in event['_embedded']['attractions'][0] else 'Unknown Genre'
                event_url = event['_embedded']['attractions'][0].get('url', '#')  # URL for the event
                event_date = event.get('dates', {}).get('start', {}).get('localDate', 'TBD')  # Event date

                event_list.append({
                    'name': name,
                    'image_url': image_url,
                    'genre': genre,
                    'event_url': event_url,
                    'event_date': event_date,
                })

            return render_template('events.html', events=event_list)
        else:
            return jsonify({"error": f"Failed to fetch events, status code: {response.status_code}"}), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/events')
def events():
    return get_events()

@app.route('/')
def home():
    return render_template('index.html')


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)