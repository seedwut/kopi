import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'coffee_secret_key'

db_url = os.environ.get('DATABASE_URL', 'sqlite:///coffee_shop.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

db = SQLAlchemy(app)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# -----------------------------------------
# Database Models
# -----------------------------------------
# ตารางสำหรับสมาชิกลูกค้า
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    points = db.Column(db.Integer, default=0) # แต้มสะสมเริ่มต้นที่ 0

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    image_file = db.Column(db.String(200), nullable=True)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(100), nullable=False)
    total_price = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(50), default='Pending') 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade="all, delete-orphan")

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False) 
    quantity = db.Column(db.Integer, default=1)   

ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'coffee1234'

def is_admin_logged_in():
    return session.get('admin_logged_in') == True

# -----------------------------------------
# ระบบสมาชิกลูกค้า (Customer Auth)
# -----------------------------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # เช็คว่ามีชื่อผู้ใช้นี้ซ้ำไหม
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash("ชื่อผู้ใช้นี้มีคนใช้แล้วครับ กรุณาใช้ชื่ออื่น", "error")
            return redirect(url_for('register'))
            
        # เข้ารหัสรหัสผ่านก่อนเซฟเพื่อความปลอดภัย
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        
        flash("สมัครสมาชิกสำเร็จ! เข้าสู่ระบบได้เลยครับ", "success")
        return redirect(url_for('login'))
    return render_template('customer_auth.html', action="register")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash(f"ยินดีต้อนรับคุณ {user.username}!", "success")
            return redirect(url_for('home'))
        else:
            flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง!", "error")
    return render_template('customer_auth.html', action="login")

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash("ออกจากระบบเรียบร้อยแล้ว", "success")
    return redirect(url_for('home'))

# -----------------------------------------
# Routes (Frontend)
# -----------------------------------------
@app.route('/')
def home():
    menu = Product.query.all()
    cart = session.get('cart', [])
    total_price = sum(item['price'] * item.get('quantity', 1) for item in cart)
    
    # ดึงข้อมูลผู้ใช้ปัจจุบันเพื่อแสดงแต้ม
    current_user = None
    if 'user_id' in session:
        current_user = User.query.get(session['user_id'])
        
    return render_template('index.html', menu=menu, cart=cart, total_price=total_price, current_user=current_user)

@app.route('/add/<int:item_id>', methods=['POST'])
def add_to_cart(item_id):
    product = Product.query.get_or_404(item_id)
    option = request.form.get('option', 'ร้อน')
    
    final_price = product.price
    if option == 'เย็น':
        final_price += 5
    elif option == 'ปั่น':
        final_price += 10
        
    item_name = f"{product.name} ({option})"
    cart = session.get('cart', [])
    
    found = False
    for item in cart:
        if item['id'] == product.id and item['name'] == item_name:
            item['quantity'] += 1  
            found = True
            break
            
    if not found:
        cart.append({
            'id': product.id, 
            'name': item_name, 
            'price': final_price,
            'quantity': 1
        })
    
    session['cart'] = cart
    return redirect(url_for('home'))

@app.route('/cart/increase/<int:index>')
def increase_cart_item(index):
    cart = session.get('cart', [])
    if 0 <= index < len(cart):
        cart[index]['quantity'] = cart[index].get('quantity', 1) + 1
        session['cart'] = cart
    return redirect(url_for('home'))

@app.route('/cart/decrease/<int:index>')
def decrease_cart_item(index):
    cart = session.get('cart', [])
    if 0 <= index < len(cart):
        cart[index]['quantity'] = cart[index].get('quantity', 1) - 1
        if cart[index]['quantity'] <= 0:
            cart.pop(index) 
        session['cart'] = cart
    return redirect(url_for('home'))

@app.route('/clear_cart')
def clear_cart():
    session.pop('cart', None)
    return redirect(url_for('home'))

@app.route('/checkout', methods=['POST'])
def checkout():
    cart = session.get('cart', [])
    if not cart:
        flash("ตะกร้าว่างเปล่า กรุณาเลือกสินค้าก่อนครับ", "error")
        return redirect(url_for('home'))
    
    # ถ้าล็อกอินอยู่ ให้ใช้ชื่อ username แต่ถ้าไม่ได้ล็อกอิน ให้รับค่าจากฟอร์ม
    customer_name = session.get('username') or request.form.get('customer_name')
    total_price = sum(item['price'] * item.get('quantity', 1) for item in cart)
    
    new_order = Order(customer_name=customer_name, total_price=total_price)
    db.session.add(new_order)
    
    # แจกแต้มสะสม (ทุก 10 บาท ได้ 1 แต้ม)
    earned_points = 0
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            earned_points = total_price // 10
            user.points += earned_points
    
    for item in cart:
        qty = item.get('quantity', 1)
        order_item = OrderItem(
            order_id=new_order.id, 
            product_name=item['name'], 
            price=item['price'] * qty,
            quantity=qty
        )
        db.session.add(order_item)
    
    db.session.commit()
    session.pop('cart', None)
    
    if earned_points > 0:
        flash(f"สั่งซื้อสำเร็จ! คุณได้รับ {earned_points} แต้มสะสม", "success")
    
    return redirect(url_for('receipt', order_id=new_order.id))

@app.route('/receipt/<int:order_id>')
def receipt(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template('receipt.html', order=order)

# -----------------------------------------
# Routes (Admin)
# -----------------------------------------
# (ส่วนนี้ยังเหมือนเดิมทุกประการ เพื่อประหยัดพื้นที่บทความครับ)
# ... ให้คุณนำโค้ด Route ส่วนของ Admin เดิมมาวางต่อตรงนี้ได้เลยครับ ...

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if is_admin_logged_in():
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USERNAME and request.form.get('password') == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Username หรือ Password ไม่ถูกต้อง!", "error")
    return render_template('login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin')
def admin_dashboard():
    if not is_admin_logged_in():
        return redirect(url_for('admin_login'))
    orders = Order.query.order_by(Order.created_at.desc()).all()
    products = Product.query.all()
    total_orders = len(orders)
    pending_orders = sum(1 for order in orders if order.status == 'Pending')
    completed_orders = sum(1 for order in orders if order.status == 'Completed')
    total_revenue = sum(order.total_price for order in orders if order.status == 'Completed')
    return render_template('admin.html', orders=orders, products=products, total_orders=total_orders, pending_orders=pending_orders, completed_orders=completed_orders, total_revenue=total_revenue)

@app.route('/admin/complete/<int:order_id>')
def complete_order(order_id):
    if is_admin_logged_in():
        order = Order.query.get_or_404(order_id)
        order.status = 'Completed'
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_order/<int:order_id>')
def delete_order(order_id):
    if not is_admin_logged_in():
        return redirect(url_for('admin_login'))
    order = Order.query.get_or_404(order_id)
    db.session.delete(order)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/add_product', methods=['POST'])
def add_product():
    if not is_admin_logged_in():
        return "Unauthorized", 403
    name = request.form.get('name')
    price = request.form.get('price')
    image = request.files.get('image') 
    filename = None
    if image and allowed_file(image.filename):
        ext = image.filename.rsplit('.', 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"
        image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    if name and price:
        new_product = Product(name=name, price=int(price), image_file=filename)
        db.session.add(new_product)
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_product/<int:product_id>')
def delete_product(product_id):
    if is_admin_logged_in():
        product = Product.query.get_or_404(product_id)
        db.session.delete(product)
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

with app.app_context():
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
