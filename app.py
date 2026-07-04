import datetime
import os
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chithub_multi_group_secure_key_2026'

# DATABASE CONNECTION MAPPING
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL or 'sqlite:///chithub_multi.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# OPTIMIZED SERVERLESS ENGINE CONFIGURATION
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 60,
    "max_overflow": 5
}

db = SQLAlchemy(app)

SECRET_CHIT_CODE = "GRAMA2026"
LIVE_BID_LOGS = {}

# ================= RELATIONAL DATA SCHEMAS =================

class User(db.Model):
    # SAFE FROM POSTGRES KEYWORD RESERVATION CONFLICTS
    __tablename__ = 'chithub_members'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(15), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default='approved') 

class ChitGroup(db.Model):
    __tablename__ = 'chit_group'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), unique=True, nullable=False) 
    total_pool = db.Column(db.Float, nullable=False)             
    total_members = db.Column(db.Integer, nullable=False)         
    agent_commission = db.Column(db.Float, default=1000.0, nullable=True) 
    current_month = db.Column(db.Integer, default=1)
    is_active = db.Column(db.Boolean, default=False)
    highest_bid = db.Column(db.Float, default=0.0)
    highest_bidder_name = db.Column(db.String(100), default="No bids placed")
    scheduled_time = db.Column(db.String(100), default="Not Scheduled")

class GroupMembership(db.Model):
    __tablename__ = 'group_membership'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    group_id = db.Column(db.Integer, db.ForeignKey('chit_group.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('chithub_members.id', ondelete='CASCADE'), nullable=False)

class ChitHistory(db.Model):
    __tablename__ = 'chit_history'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    group_id = db.Column(db.Integer, db.ForeignKey('chit_group.id'))
    month_number = db.Column(db.Integer)
    winner_name = db.Column(db.String(100))
    winning_bid = db.Column(db.Float)
    payable_per_member = db.Column(db.Float)
    payout_to_winner = db.Column(db.Float)
    agent_fee = db.Column(db.Float, default=1000.0)             
    dividend_per_head = db.Column(db.Float, default=0.0)        

class LiveBidTrail(db.Model):
    __tablename__ = 'live_bid_trail'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    group_id = db.Column(db.Integer, nullable=False)
    bidder_name = db.Column(db.String(100))
    increment_value = db.Column(db.Float)
    running_total = db.Column(db.Float)
    timestamp = db.Column(db.String(30))

# CLEAN UP SESSIONS TO PREVENT CONCURRENCY LOCKS
@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session.remove()

with app.app_context():
    db.create_all()
    if not User.query.filter_by(phone="9686193049").first():
        db.session.add(User(name="Chit Organizer", phone="9686193049", password_hash=generate_password_hash("Life@789", method='pbkdf2:sha256'), status="admin"))
        db.session.commit()

# ================= AUTHENTICATION MAPS =================

@app.route('/')
def index():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('index'))
    if session.get('user_status') == 'admin':
        return render_template('multi_admin.html', admin_name=session.get('user_name'), groups=ChitGroup.query.order_by(ChitGroup.id.desc()).all())
    
    allocated_groups = db.session.query(ChitGroup).join(GroupMembership, ChitGroup.id == GroupMembership.group_id).filter(GroupMembership.user_id == session['user_id']).order_by(ChitGroup.id.desc()).all()
    return render_template('member_room.html', user_name=session.get('user_name'), groups=allocated_groups)

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json() or {}
        name, phone, password, access_code = data.get('name'), data.get('phone'), data.get('password'), data.get('access_code')
        
        if not all([name, phone, password, access_code]) or access_code.strip().upper() != SECRET_CHIT_CODE:
            return jsonify({'success': False, 'message': 'Validation error. Check input fields.'}), 400
            
        existing_user = User.query.filter_by(phone=phone).first()
        if existing_user: 
            return jsonify({'success': False, 'message': 'This mobile number is already registered.'}), 400
            
        new_user = User(name=name, phone=phone, password_hash=generate_password_hash(password, method='pbkdf2:sha256'))
        db.session.add(new_user)
        db.session.commit()
        return jsonify({'success': True}), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f"Server/Database Error: {str(e)}"}), 500

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    u = User.query.filter_by(phone=data.get('phone')).first()
    if not u or not check_password_hash(u.password_hash, data.get('password')): return jsonify({'success': False, 'message': 'Invalid credentials.'}), 401
    session['user_id'], session['user_name'], session['user_status'] = u.id, u.name, u.status
    return jsonify({'success': True, 'redirect': url_for('dashboard')}), 200

# ================= STATE POLL SYNCHRONIZER REST ENDPOINTS =================

@app.route('/api/chit/room-state/<int:group_id>')
def get_room_state(group_id):
    g = ChitGroup.query.get(group_id)
    if not g: return jsonify({'success': False}), 404
    trails = LiveBidTrail.query.filter_by(group_id=group_id).order_by(LiveBidTrail.id.asc()).all()
    return jsonify({
        'success': True, 'is_active': g.is_active, 'highest_bid': g.highest_bid, 
        'highest_bidder': g.highest_bidder_name, 'current_month': g.current_month,
        'bids': [{'name': t.bidder_name, 'increment': t.increment_value, 'total': t.running_total, 'time': t.timestamp} for t in trails]
    })

@app.route('/api/chit/place-bid', methods=['POST'])
def place_bid():
    if 'user_id' not in session: return jsonify({'success': False}), 403
    data = request.get_json() or {}
    g = ChitGroup.query.get(int(data.get('group_id', 0)))
    if not g or not g.is_active: return jsonify({'success': False, 'message': 'Room inactive'}), 400
    
    increment = float(data.get('increment', 0))
    proxy_name = data.get('proxy_name')
    bidder = f"{proxy_name} (Offline)" if (proxy_name and session.get('user_status') == 'admin') else session.get('user_name')
    
    g.highest_bid += increment
    g.highest_bidder_name = bidder
    
    trail = LiveBidTrail(group_id=g.id, bidder_name=bidder, increment_value=increment, running_total=g.highest_bid, timestamp=datetime.datetime.now().strftime('%H:%M:%S'))
    db.session.add(trail)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/admin/room-control', methods=['POST'])
def room_control():
    if session.get('user_status') != 'admin': return jsonify({'success': False}), 403
    data = request.get_json() or {}
    g = ChitGroup.query.get(int(data.get('group_id', 0)))
    action = data.get('action')
    if not g: return jsonify({'success': False}), 404
    
    if action == 'start':
        g.is_active, g.highest_bid, g.highest_bidder_name = True, 0.0, "No bids placed yet"
        LiveBidTrail.query.filter_by(group_id=g.id).delete()
        db.session.commit()
    elif action == 'finalize':
        if g.is_active:
            g.is_active = False
            base_installment = g.total_pool / g.total_members  
            past_winners_count = db.session.query(db.func.count(ChitHistory.id)).filter_by(group_id=g.id).scalar()
            dividend_sharing_members = (g.total_members - past_winners_count) - 1 
            net_dividend_pool = g.highest_bid - 1000.0 
            dividend_discount = (net_dividend_pool / dividend_sharing_members) if dividend_sharing_members > 0 else 0.0
            
            h = ChitHistory(group_id=g.id, month_number=g.current_month, winner_name=g.highest_bidder_name, winning_bid=g.highest_bid, payable_per_member=round(base_installment - dividend_discount, 2), payout_to_winner=round(g.total_pool - g.highest_bid, 2), agent_fee=1000.0, dividend_per_head=round(dividend_discount, 2))
            g.current_month += 1
            LiveBidTrail.query.filter_by(group_id=g.id).delete()
            db.session.add(h)
            db.session.commit()
            
    return jsonify({'success': True})

# ================= DATA CONTEXT MANAGER CORE API NODES =================

@app.route('/api/admin/inject-history', methods=['POST'])
def inject_history():
    if session.get('user_status') != 'admin': return jsonify({'success': False}), 403
    data = request.get_json() or {}
    try:
        group_id, month = int(data.get('group_id')), int(data.get('month'))
        winner_name, winning_bid = data.get('winner_name'), float(data.get('winning_bid'))
        g = ChitGroup.query.get(group_id)
        if not g: return jsonify({'success': False}), 404
        
        base_installment = g.total_pool / g.total_members  
        dividend_sharing_members = (g.total_members - (month - 1)) - 1 
        dividend_discount = ((winning_bid - 1000.0) / dividend_sharing_members) if dividend_sharing_members > 0 else 0.0

        h = ChitHistory(group_id=g.id, month_number=month, winner_name=winner_name, winning_bid=winning_bid, payable_per_member=round(base_installment - dividend_discount, 2), payout_to_winner=round(g.total_pool - winning_bid, 2), agent_fee=1000.0, dividend_per_head=round(dividend_discount, 2))
        if month >= g.current_month: g.current_month = month + 1
        db.session.add(h)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e: return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/delete-history/<int:history_id>', methods=['POST'])
def delete_history(history_id):
    if session.get('user_status') != 'admin': return jsonify({'success': False}), 403
    h = ChitHistory.query.get(history_id)
    if h:
        group_id = h.group_id
        db.session.delete(h)
        remaining = ChitHistory.query.filter_by(group_id=group_id).order_by(ChitHistory.month_number.desc()).first()
        g = ChitGroup.query.get(group_id)
        if g: g.current_month = (remaining.month_number + 1) if remaining else 1
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False}), 404

@app.route('/api/admin/create-group', methods=['POST'])
def create_group():
    if session.get('user_status') != 'admin': return jsonify({'success': False}), 403
    data = request.get_json() or {}
    db.session.add(ChitGroup(name=data.get('name'), total_pool=float(data.get('pool')), total_members=int(data.get('members'))))
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/admin/schedule-group', methods=['POST'])
def schedule_group():
    if session.get('user_status') != 'admin': return jsonify({'success': False}), 403
    data = request.get_json() or {}
    g = ChitGroup.query.get(int(data.get('group_id')))
    if g: g.scheduled_time = f"{data.get('date')} at {data.get('time')}"; db.session.commit()
    return jsonify({'success': True})

@app.route('/api/admin/group-members/<int:group_id>')
def get_group_members(group_id):
    if session.get('user_status') != 'admin': return jsonify({'success': False}), 403
    all_users = User.query.filter(User.status != 'admin').all()
    mapped_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=group_id).all()]
    return jsonify({'success': True, 'users': [{'id': u.id, 'name': u.name, 'phone': u.phone, 'is_member': (u.id in mapped_ids)} for u in all_users]})

@app.route('/api/update-membership', methods=['POST'])
def update_membership():
    if session.get('user_status') != 'admin': return jsonify({'success': False}), 403
    data = request.get_json() or {}
    group_id, selected_user_ids = int(data.get('group_id')), [int(uid) for uid in data.get('user_ids', [])]
    GroupMembership.query.filter_by(group_id=group_id).delete()
    for uid in selected_user_ids: db.session.add(GroupMembership(group_id=group_id, user_id=uid))
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/chit/history/<int:group_id>')
def get_group_history(group_id):
    records = ChitHistory.query.filter_by(group_id=group_id).order_by(ChitHistory.month_number.asc()).all()
    g = ChitGroup.query.get(group_id)
    return jsonify({'success': True, 'base_installment': (g.total_pool / g.total_members) if g else 0, 'history': [{'id': r.id, 'month': r.month_number, 'winner': r.winner_name, 'bid': r.winning_bid, 'due_non_winner': r.payable_per_member, 'payout': r.payout_to_winner, 'agent_fee': r.agent_fee, 'dividend_per_head': r.dividend_per_head} for r in records]})

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('index'))
