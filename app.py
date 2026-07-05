import datetime
import os
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chithub_multi_group_secure_key_2026'

# PRODUCTION DATABASE ROUTER
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL or 'sqlite:///chithub_multi.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

SECRET_CHIT_CODE = "GRAMA2026"
LIVE_BID_LOGS = {} 

# ================= RELATIONAL DATA SCHEMAS =================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(15), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default='approved') 

class ChitGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
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
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('chit_group.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)

class ChitHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('chit_group.id', ondelete='CASCADE'))
    month_number = db.Column(db.Integer)
    winner_name = db.Column(db.String(100))
    winning_bid = db.Column(db.Float)
    payable_per_member = db.Column(db.Float)
    payout_to_winner = db.Column(db.Float)
    agent_fee = db.Column(db.Float, default=1000.0)             
    dividend_per_head = db.Column(db.Float, default=0.0)        

# ================= DATABASE INITIALIZATION =================

with app.app_context():
    db.create_all()
    if not User.query.filter_by(phone="9999999999").first():
        db.session.add(User(
            name="Chit Organizer", 
            phone="9999999999", 
            password_hash=generate_password_hash("admin123", method='pbkdf2:sha256'), 
            status="admin"
        ))
        db.session.commit()

# ================= PUBLIC & PRIVATE ROUTING VIEWS =================

# 1. NEW FRONT ENTRY DOOR: Public Modern Landing Page
@app.route('/')
def index():
    if 'user_id' in session: 
        return redirect(url_for('dashboard'))
    return render_template('index.html')

# 2. SEPARATED GATEWAY: Dedicated Login/Register Frame Page
@app.route('/login')
def login_view():
    if 'user_id' in session: 
        return redirect(url_for('dashboard'))
    return render_template('login.html')

# 3. INTERIOR SECURE REGION: Dashboards Router
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: 
        return redirect(url_for('login_view'))
        
    if session.get('user_status') == 'admin':
        return render_template('multi_admin.html', admin_name=session.get('user_name'), groups=ChitGroup.query.all())
    
    allocated_groups = db.session.query(ChitGroup).join(
        GroupMembership, ChitGroup.id == GroupMembership.group_id
    ).filter(GroupMembership.user_id == session['user_id']).all()
    
    return render_template('member_room.html', user_name=session.get('user_name'), groups=allocated_groups)

# ================= CONTROLLER HANDLING APIS =================

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    name, phone, password, access_code = data.get('name'), data.get('phone'), data.get('password'), data.get('access_code')
    if not all([name, phone, password, access_code]) or access_code.strip().upper() != SECRET_CHIT_CODE:
        return jsonify({'success': False, 'message': 'Validation error.'}), 400
    if User.query.filter_by(phone=phone).first():
        return jsonify({'success': False, 'message': 'Already registered.'}), 400

    try:
        db.session.add(User(name=name, phone=phone, password_hash=generate_password_hash(password, method='pbkdf2:sha256')))
        db.session.commit()
        return jsonify({'success': True, 'message': 'Profile built successfully.'}), 201
    except:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Database error.'}), 500

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    u = User.query.filter_by(phone=data.get('phone')).first()
    if not u or not check_password_hash(u.password_hash, data.get('password')):
        return jsonify({'success': False, 'message': 'Invalid credentials.'}), 401
    session['user_id'], session['user_name'], session['user_status'] = u.id, u.name, u.status
    return jsonify({'success': True, 'redirect': url_for('dashboard')}), 200

# ================= RUNTIME MONITORING ENDPOINTS =================

@app.route('/api/chit/room-state/<int:group_id>')
def room_state(group_id):
    g = ChitGroup.query.get(group_id)
    if not g:
        return jsonify({'success': False, 'message': 'Not Found'}), 404
    
    room_key = str(group_id)
    bids = LIVE_BID_LOGS.get(room_key, [])
    
    return jsonify({
        'success': True,
        'is_active': g.is_active,
        'highest_bid': g.highest_bid,
        'highest_bidder': g.highest_bidder_name,
        'current_month': g.current_month,
        'bids': bids
    })

@app.route('/api/admin/room-control', methods=['POST'])
def room_control():
    if session.get('user_status') != 'admin': 
        return jsonify({'success': False}), 403
    
    data = request.get_json()
    group_id = int(data.get('group_id'))
    action = data.get('action')
    
    g = ChitGroup.query.get(group_id)
    if not g:
        return jsonify({'success': False, 'message': 'Group not found'}), 404
        
    if action == 'start':
        g.is_active = True
        g.highest_bid = 0.0
        g.highest_bidder_name = "No bids placed yet"
        db.session.commit()
        LIVE_BID_LOGS[str(g.id)] = []
        socketio.emit('room_opened', {'group_id': g.id, 'highest_bid': 0.0, 'highest_bidder': "No bids placed yet"}, to=str(g.id))
        return jsonify({'success': True})
        
    elif action == 'finalize':
        if g.is_active:
            g.is_active = False
            base_installment = g.total_pool / g.total_members  
            past_winners_count = ChitHistory.query.filter_by(group_id=g.id).count()
            dividend_sharing_members = (g.total_members - past_winners_count) - 1 
            AGENT_FIXED_FEE = 1000.0
            net_dividend_pool = g.highest_bid - AGENT_FIXED_FEE 
            dividend_discount = (net_dividend_pool / dividend_sharing_members) if dividend_sharing_members > 0 else 0.0
            final_due_for_non_winners = base_installment - dividend_discount
            final_payout = g.total_pool - g.highest_bid

            try:
                h = ChitHistory(group_id=g.id, month_number=g.current_month, winner_name=g.highest_bidder_name, winning_bid=g.highest_bid, payable_per_member=round(final_due_for_non_winners, 2), payout_to_winner=round(final_payout, 2), agent_fee=AGENT_FIXED_FEE, dividend_per_head=round(dividend_discount, 2))
                g.current_month += 1
                db.session.add(h)
                db.session.commit()
                if str(g.id) in LIVE_BID_LOGS: 
                    del LIVE_BID_LOGS[str(g.id)]
                socketio.emit('room_closed', {'group_id': g.id}, to=str(g.id))
                return jsonify({'success': True})
            except Exception as e: 
                db.session.rollback()
                return jsonify({'success': False, 'message': str(e)}), 500
                
    return jsonify({'success': False, 'message': 'Invalid action'}), 400

@app.route('/api/chit/place-bid', methods=['POST'])
def api_place_bid():
    data = request.get_json()
    g = ChitGroup.query.get(int(data.get('group_id')))
    if not g or not g.is_active: 
        return jsonify({'success': False}), 400
        
    increment = float(data.get('increment', 0))
    proxy_name = data.get('proxy_name')
    bidder = f"{proxy_name} (Offline)" if proxy_name else session.get('user_name')
    
    g.highest_bid += increment
    g.highest_bidder_name = bidder
    db.session.commit()
    
    log_payload = {'group_id': g.id, 'name': bidder, 'increment': increment, 'total': g.highest_bid, 'timestamp': datetime.datetime.now().strftime('%H:%M:%S')}
    if str(g.id) not in LIVE_BID_LOGS: 
        LIVE_BID_LOGS[str(g.id)] = []
    LIVE_BID_LOGS[str(g.id)].append(log_payload)
    
    socketio.emit('bid_broadcast', {'group_id': g.id, 'highest_bid': g.highest_bid, 'highest_bidder': g.highest_bidder_name}, to=str(g.id))
    socketio.emit('single_log_append', log_payload, to=str(g.id))
    return jsonify({'success': True})

# ---------------- PREVIOUS RECORDS INJECTOR ----------------

@app.route('/api/admin/inject-history', methods=['POST'])
def inject_history():
    if session.get('user_status') != 'admin': return jsonify({'success': False}), 403
    data = request.get_json()
    
    try:
        group_id = int(data.get('group_id'))
        month = int(data.get('month'))
        winner_name = data.get('winner_name')
        winning_bid = float(data.get('winning_bid'))
        
        g = ChitGroup.query.get(group_id)
        if not g: return jsonify({'success': False, 'message': 'Group not found.'}), 404
        
        base_installment = g.total_pool / g.total_members  
        past_winners_count = month - 1
        
        dividend_sharing_members = (g.total_members - past_winners_count) - 1 
        AGENT_FIXED_FEE = 1000.0
        net_dividend_pool = winning_bid - AGENT_FIXED_FEE 
        
        dividend_discount = (net_dividend_pool / dividend_sharing_members) if dividend_sharing_members > 0 else 0.0
        final_due_for_non_winners = base_installment - dividend_discount
        final_payout = g.total_pool - winning_bid

        h = ChitHistory(
            group_id=g.id, month_number=month, winner_name=winner_name,
            winning_bid=winning_bid, payable_per_member=round(final_due_for_non_winners, 2), 
            payout_to_winner=round(final_payout, 2), agent_fee=AGENT_FIXED_FEE, dividend_per_head=round(dividend_discount, 2)
        )
        
        if month >= g.current_month:
            g.current_month = month + 1
            
        db.session.add(h)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

# ---------------- ADMINISTRATIVE PRIVILEGE PATHS ----------------

@app.route('/api/admin/create-group', methods=['POST'])
def create_group():
    if session.get('user_status') != 'admin': return jsonify({'success': False}), 403
    data = request.get_json()
    try:
        db.session.add(ChitGroup(name=data.get('name'), total_pool=float(data.get('pool')), total_members=int(data.get('members')), agent_commission=1000.0))
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/schedule-group', methods=['POST'])
def schedule_group():
    if session.get('user_status') != 'admin': return jsonify({'success': False}), 403
    data = request.get_json()
    g = ChitGroup.query.get(int(data.get('group_id')))
    if g: g.scheduled_time = f"{data.get('date')} at {data.get('time')}"; db.session.commit()
    return jsonify({'success': True})

@app.route('/api/admin/group-members/<int:group_id>')
def get_group_members(group_id):
    if session.get('user_status') != 'admin': return jsonify({'success': False}), 403
    all_users = User.query.filter(User.status != 'admin').all()
    mapped_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=group_id).all()]
    return jsonify({'success': True, 'users': [{'id': u.id, 'name': u.name, 'phone': u.phone, 'is_member': (u.id in mapped_ids)} for u in all_users]})

@app.route('/api/admin/update-membership', methods=['POST'])
def update_membership():
    if session.get('user_status') != 'admin': return jsonify({'success': False}), 403
    data = request.get_json()
    group_id, selected_user_ids = int(data.get('group_id')), [int(uid) for uid in data.get('user_ids', [])]
    try:
        GroupMembership.query.filter_by(group_id=group_id).delete()
        for uid in selected_user_ids: db.session.add(GroupMembership(group_id=group_id, user_id=uid))
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/chit/history/<int:group_id>')
def get_group_history(group_id):
    records = ChitHistory.query.filter_by(group_id=group_id).order_by(ChitHistory.month_number.asc()).all()
    g = ChitGroup.query.get(group_id)
    return jsonify({'success': True, 'base_installment': (g.total_pool / g.total_members) if g else 0, 'history': [{'month': r.month_number, 'winner': r.winner_name, 'bid': r.winning_bid, 'due_non_winner': r.payable_per_member, 'payout': r.payout_to_winner, 'agent_fee': r.agent_fee, 'dividend_per_head': r.dividend_per_head} for r in records]})

@app.route('/api/admin/delete-group/<int:group_id>', methods=['POST'])
def delete_group(group_id):
    if session.get('user_status') != 'admin': 
        return jsonify({'success': False}), 403
    try:
        g = ChitGroup.query.get(group_id)
        if g:
            db.session.delete(g)
            db.session.commit()
            return jsonify({'success': True})
        return jsonify({'success': False, 'message': 'Group not found'}), 404
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/logout')
def logout(): 
    session.clear()
    return redirect(url_for('index'))

# ================= REALTIME SOCKET ENGINE =================

@socketio.on('join_chit_room')
def on_join(data):
    try:
        room = str(data['group_id'])
        join_room(room)
        if room in LIVE_BID_LOGS:
            for log in LIVE_BID_LOGS[room]: emit('single_log_append', log, to=request.sid)
    except: pass

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)
