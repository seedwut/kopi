from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, timedelta
import os
import uuid
import requests
import cloudinary
import cloudinary.uploader
import cloudinary.api

app = Flask(__name__)
app.secret_key = 'kopi_super_secret_key'

# 📌 ตั้งค่า Cloudinary (เอาค่าจากเว็บ Cloudinary มาใส่ตรงนี้ครับ)
cloudinary.config( 
  cloud_name = "ใส่_CLOUD_NAME_ของคุณ", 
  api_key = "ใส่_API_KEY_ของคุณ", 
  api_secret = "ใส่_API_SECRET_ของคุณ" 
)

# 📌 ตั้งค่าฐานข้อมูล: ใช้ PostgreSQL บน Cloud หรือใช้ SQLite ตอนทำในคอม
db_url = os.environ.get('DATABASE_URL', 'sqlite:///coffee_shop.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 📌 ฟังก์ชันอ่านและบันทึกสถานะร้าน
def is_shop_open():
    if not os.path.exists('shop_status.txt'): 
        return True
    with open('shop_status.txt', 'r') as f: 
        return f.read().strip() == 'open'

def set_shop_status(status):
    with open('shop_status.txt', 'w') as f: 
        f.write(status)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ==========================================
# 1. โครงสร้างฐานข้อมูล (Models)
# ==========================================
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    image_file = db.Column(db.String(200), nullable=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    points = db.Column(db.Integer, default=0)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    queue_number = db.Column(db.String(10), nullable=True)
    customer_name = db.Column(db.String(100), nullable=False)
    total_price = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(50), default='Pending') 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    slip_image = db.Column(db.String(500), nullable=True) # ขยายขนาดเผื่อลิงก์ Cloudinary ยาว
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade="all, delete-orphan")

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, default=1)
    sweetness = db.Column(db.String(20), default='100%')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}

def is_admin_logged_in():
    return session.get('admin_logged_in') == True

# ==========================================
# 2. ระบบหน้าร้านและสมาชิก
# ==========================================
@app.route('/')
def home():
    cart = session.get('cart', [])
    current_user = None
    if 'user_id' in session:
        current_user = User.query.get(session['user_id'])
    
    products = Product.query.all()
    return render_template('index.html', products=products, cart=cart, current_user=current_user, shop_open=is_shop_open())

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash("ชื่อผู้ใช้นี้มีคนใช้แล้ว!", "error")
            return redirect(url_for('register'))
            
        db.session.add(User(username=username, password=password))
        db.session.commit()
        flash("สมัครสมาชิกสำเร็จ! กรุณาเข้าสู่ระบบ", "success")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username'), password=request.form.get('password')).first()
        if user:
            session['user_id'] = user.id
            session['username'] = user.username
            flash(f"ยินดีต้อนรับคุณ {user.username}", "success")
            return redirect(url_for('home'))
        flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", "error")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash("ออกจากระบบเรียบร้อย", "success")
    return redirect(url_for('home'))

# ==========================================
# 3. ระบบสั่งซื้อและตะกร้า
# ==========================================
@app.route('/add/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    product = Product.query.get(product_id)
    if product:
        sweetness = request.form.get('sweetness', '100%')
        drink_type = request.form.get('drink_type', 'เย็น')
        final_price = product.price
        
        cart = session.get('cart', [])
        found = False
        for item in cart:
            if item['id'] == product.id and item.get('sweetness') == sweetness and item.get('drink_type') == drink_type:
                item['quantity'] = item.get('quantity', 1) + 1
                found = True
                break
                
        if not found:
            cart.append({'id': product.id, 'name': product.name, 'price': final_price, 'quantity': 1, 'sweetness': sweetness, 'drink_type': drink_type})
            
        session['cart'] = cart
        session.modified = True
        flash(f"เพิ่ม {product.name} ({drink_type}) ลงตะกร้าแล้ว", "success")
    return redirect(url_for('home'))

@app.route('/checkout', methods=['POST'])
def checkout():
    cart = session.get('cart', [])
    if not cart:
        flash("ตะกร้าว่างเปล่า กรุณาเลือกสินค้าก่อนครับ", "error")
        return redirect(url_for('home'))
    
    customer_name = session.get('username') or request.form.get('customer_name')
    total_price = sum(item['price'] * item.get('quantity', 1) for item in cart)
    discount = 0
    
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if request.form.get('use_points') and user.points >= 50:
            user.points -= 50
            discount = 10
            flash("ใช้ 50 แต้ม แลกส่วนลด 10 บาทเรียบร้อย!", "success")
            
    final_total = max(0, total_price - discount)
    
    # 📌 ระบบคำนวณคิว
    thai_time = datetime.utcnow() + timedelta(hours=7)
    start_of_day_utc = datetime(thai_time.year, thai_time.month, thai_time.day) - timedelta(hours=7)
    today_orders_count = Order.query.filter(Order.created_at >= start_of_day_utc).count()
    new_queue = f"Q{today_orders_count + 1:02d}"
    
    new_order = Order(customer_name=customer_name, total_price=final_total, queue_number=new_queue)
    db.session.add(new_order)
    db.session.flush() 
    
    earned_points = 0
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            earned_points = final_total // 10
            user.points += earned_points
    
    msg = f"☕ มีออเดอร์ใหม่! (คิว {new_queue})\n👤 ลูกค้า: {customer_name}\n💰 ยอดรวม: {final_total} บาท\n📝 รายการ:\n"
    
    for item in cart:
        qty = item.get('quantity', 1)
        sw = item.get('sweetness', '100%')
        db.session.add(OrderItem(order_id=new_order.id, product_name=item['name'], price=item['price'] * qty, quantity=qty, sweetness=sw))
        msg += f"- {item['name']} (หวาน {sw}) x{qty}\n"
    
    db.session.commit()
    
    # 📌 ระบบส่ง LINE
    try:
        line_token = "NRscL9JJEUEHOp9jn8hmKjhFJc7zCmJdAPwQ02UxICcjlncwiHbwcIiOTzR7JkoQZpugb++0k0nkhm4gbmkE9i4dIhXQ63nwkw7IO1MI4KjwNcw11IpGrdE1Ntcy4uHrow2BcesRH6pTjsjIZd5RGgdB04t89/1O/w1cDnyilFU="
        admin_user_id = "Ue3c076dc502fc6fc8f03566806705e7e"
        requests.post("https://api.line.me/v2/bot/message/push", headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {line_token}'}, json={"to": admin_user_id, "messages": [{"type": "text", "text": msg}]})
    except: pass

    session.pop('cart', None)
    if earned_points > 0: flash(f"สั่งซื้อสำเร็จ! ได้รับ {earned_points} แต้มสะสม", "success")
    return redirect(url_for('receipt', order_id=new_order.id))

# ==========================================
# 4. ระบบชำระเงินและสลิป (Cloudinary)
# ==========================================
@app.route('/receipt/<int:order_id>')
def receipt(order_id):
    return render_template('receipt.html', order=Order.query.get_or_404(order_id), promptpay_number="0812345678")

@app.route('/upload_slip/<int:order_id>', methods=['POST'])
def upload_slip(order_id):
    order = Order.query.get_or_404(order_id)
    slip = request.files.get('slip')
    if slip and allowed_file(slip.filename):
        # 📌 อัปโหลดสลิปขึ้น Cloudinary
        upload_result = cloudinary.uploader.upload(slip)
        order.slip_image = upload_result.get('secure_url')
        
        order.status = 'Paid'
        db.session.commit()
        flash("แนบสลิปเรียบร้อยแล้ว!", "success")
    return redirect(url_for('receipt', order_id=order.id))

@app.route('/history')
def history():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_orders = Order.query.filter_by(customer_name=session['username']).order_by(Order.created_at.desc()).all()
    return render_template('history.html', orders=user_orders, current_user=User.query.get(session['user_id']))

# ==========================================
# 5. ระบบหลังร้าน (Admin Dashboard)
# ==========================================
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('username') == 'admin' and request.form.get('password') == '1234':
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        flash("ข้อมูลแอดมินไม่ถูกต้อง", "error")
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin')
def admin_dashboard():
    if not is_admin_logged_in(): return redirect(url_for('admin_login'))
    orders = Order.query.order_by(Order.created_at.desc()).all()
    
    today = datetime.utcnow().date()
    date_dict = {}
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        date_dict[day.strftime('%d/%m')] = 0
        
    for o in orders:
        if o.status == 'Completed':
            order_date = o.created_at.date().strftime('%d/%m')
            if order_date in date_dict:
                date_dict[order_date] += o.total_price
                
    sales_labels = list(date_dict.keys())
    sales_values = list(date_dict.values())

    return render_template('admin.html', 
                           orders=orders, 
                           total_orders=len(orders), 
                           pending_orders=sum(1 for o in orders if o.status in ['Pending', 'Paid', 'Brewing', 'Ready']), 
                           total_revenue=sum(o.total_price for o in orders if o.status == 'Completed'),
                           products=Product.query.all(),
                           users=User.query.all(),
                           shop_open=is_shop_open(),
                           sales_labels=sales_labels,
                           sales_values=sales_values)

@app.route('/admin/toggle_status')
def toggle_status():
    if not is_admin_logged_in(): return redirect(url_for('admin_login'))
    current_status = is_shop_open()
    set_shop_status('closed' if current_status else 'open')
    flash("อัปเดตสถานะร้านเรียบร้อยแล้ว!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reset_password/<int:user_id>', methods=['POST'])
def admin_reset_password(user_id):
    if not is_admin_logged_in(): return redirect(url_for('admin_login'))
    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password')
    if new_password:
        user.password = new_password
        db.session.commit()
        flash(f"เปลี่ยนรหัสผ่านให้คุณ {user.username} เรียบร้อย!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_user/<int:user_id>')
def admin_delete_user(user_id):
    if not is_admin_logged_in(): return redirect(url_for('admin_login'))
    user = User.query.get_or_404(user_id)
    username = user.username
    db.session.delete(user)
    db.session.commit()
    flash(f"ลบบัญชีผู้ใช้ {username} ออกจากระบบเรียบร้อยแล้ว", "success")
    return redirect(url_for('admin_dashboard'))
                           
@app.route('/admin/add_product', methods=['POST'])
def add_product():
    if not is_admin_logged_in(): return redirect(url_for('admin_login'))
    name = request.form.get('name')
    price = request.form.get('price')
    image = request.files.get('image')
    
    image_url = None
    if image and allowed_file(image.filename):
        # 📌 อัปโหลดรูปเมนูขึ้น Cloudinary
        upload_result = cloudinary.uploader.upload(image)
        image_url = upload_result.get('secure_url')

    if name and price:
        db.session.add(Product(name=name, price=int(price), image_file=image_url))
        db.session.commit()
        flash(f"เพิ่มเมนู {name} ลงในร้านเรียบร้อย!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit_product/<int:product_id>', methods=['POST'])
def edit_product(product_id):
    if not is_admin_logged_in(): return redirect(url_for('admin_login'))
    product = Product.query.get_or_404(product_id)
    
    product.name = request.form.get('name', product.name)
    product.price = request.form.get('price', product.price)
    
    image = request.files.get('image')
    if image and allowed_file(image.filename):
        # 📌 อัปโหลดรูปเมนูใหม่ขึ้น Cloudinary
        upload_result = cloudinary.uploader.upload(image)
        product.image_file = upload_result.get('secure_url')
        
    db.session.commit()
    flash(f"อัปเดตข้อมูลเมนู {product.name} เรียบร้อย!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_product/<int:product_id>')
def delete_product(product_id):
    if not is_admin_logged_in(): return redirect(url_for('admin_login'))
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash("ลบเมนูออกจากร้านเรียบร้อย!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/complete/<int:order_id>')
def complete_order(order_id):
    if not is_admin_logged_in(): return redirect(url_for('admin_login'))
    order = Order.query.get_or_404(order_id)
    order.status = 'Completed'
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete/<int:order_id>')
def delete_order(order_id):
    if not is_admin_logged_in(): return redirect(url_for('admin_login'))
    order = Order.query.get_or_404(order_id)
    db.session.delete(order)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/check_updates')
def check_updates():
    if not is_admin_logged_in(): return {"error": "Unauthorized"}, 403
    latest = Order.query.order_by(Order.id.desc()).first()
    return {"latest_id": latest.id if latest else 0}

@app.route('/admin/print/<int:order_id>')
def print_receipt(order_id):
    if not is_admin_logged_in(): 
        return redirect(url_for('admin_login'))
    order = Order.query.get_or_404(order_id)
    return render_template('print_receipt.html', order=order)
    
@app.route('/admin/update_status/<int:order_id>/<status>')
def update_order_status(order_id, status):
    if not is_admin_logged_in(): return redirect(url_for('admin_login'))
    
    order = Order.query.get_or_404(order_id)
    if status in ['Pending', 'Paid', 'Brewing', 'Ready', 'Completed']:
        order.status = status
        db.session.commit()
        
    return redirect(url_for('admin_dashboard'))

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
