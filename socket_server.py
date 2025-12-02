import socketio
import eventlet
import json
import time
from flask import Flask, request, jsonify

print("🚀 Starting Socket.IO server...")

# Create a Flask app for HTTP endpoints
flask_app = Flask(__name__)

# Create a Socket.IO server instance
# Allow all origins for development (you can restrict this in production)
sio = socketio.Server(
    cors_allowed_origins="*",  # Allow all origins for development
    async_mode='eventlet'
)

# Create a Socket.IO application
app = socketio.WSGIApp(sio, flask_app)

# Store connected clients
connected_clients = {}

# HTTP endpoints for Django communication
@flask_app.route('/emit_new_order', methods=['POST'])
def emit_new_order_endpoint():
    """HTTP endpoint for Django to emit new order events"""
    try:
        data = request.get_json()
        order_data = data.get('order')
        print(f"🆕 HTTP: New order received from Django: {order_data.get('id', 'unknown')}")
        
        # Emit to admin and staff rooms
        sio.emit('new_order', {
            'order': order_data,
            'message': 'New order received!'
        }, room='admin')
        
        sio.emit('new_order', {
            'order': order_data,
            'message': 'New order received!'
        }, room='staff')
        
        return jsonify({'success': True, 'message': 'New order event emitted'})
    except Exception as e:
        print(f"❌ Error emitting new order: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@flask_app.route('/emit_order_update', methods=['POST'])
def emit_order_update_endpoint():
    """HTTP endpoint for Django to emit order status update events"""
    try:
        data = request.get_json()
        order_id = data.get('order_id')
        new_status = data.get('status')
        user_type = data.get('user_type', 'admin')
        
        print(f"📋 HTTP: Order {order_id} status update to {new_status} by {user_type}")
        
        # Broadcast to all connected clients
        sio.emit('order_updated', {
            'order_id': order_id,
            'status': new_status,
            'updated_by': user_type,
            'message': f'Order #{order_id} status changed to {new_status}'
        })
        
        return jsonify({'success': True, 'message': 'Order update event emitted'})
    except Exception as e:
        print(f"❌ Error emitting order update: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@flask_app.route('/emit_waiter_call', methods=['POST'])
def emit_waiter_call_endpoint():
    """HTTP endpoint for Django to emit waiter call events"""
    try:
        data = request.get_json()
        table_number = data.get('table_number')
        table_unique_id = data.get('table_unique_id')
        room_unique_id = data.get('room_unique_id')
        message = data.get('message', '')
        
        call_id = f"call_{table_unique_id}_{int(time.time())}"
        
        print(f"🔔 HTTP: Waiter call from table {table_number} (ID: {call_id})")
        
        # Emit to waiters room
        sio.emit('waiter_call', {
            'id': call_id,
            'table_number': table_number,
            'table_unique_id': table_unique_id,
            'room_unique_id': room_unique_id,
            'timestamp': time.time(),
            'status': 'pending',
            'customer_message': message
        }, room='waiters')
        
        return jsonify({'success': True, 'call_id': call_id, 'message': 'Waiter call event emitted'})
    except Exception as e:
        print(f"❌ Error emitting waiter call: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@sio.event
def connect(sid, environ):
    """Handle client connection"""
    print(f"✅ Client connected: {sid}")
    connected_clients[sid] = {
        'sid': sid,
        'user_type': None,
        'room': None
    }
    
    # Send welcome message
    sio.emit('welcome', {'message': 'Connected to Restaurant Management System'}, room=sid)

@sio.event
def disconnect(sid):
    """Handle client disconnection"""
    print(f"❌ Client disconnected: {sid}")
    if sid in connected_clients:
        del connected_clients[sid]

@sio.event
def join_room(sid, data):
    """Join a specific room (e.g., admin, staff, table-specific)"""
    room = data.get('room', 'general')
    user_type = data.get('user_type', 'customer')
    
    if sid in connected_clients:
        connected_clients[sid]['room'] = room
        connected_clients[sid]['user_type'] = user_type
    
    sio.enter_room(sid, room)
    print(f"🏠 Client {sid} joined room: {room} as {user_type}")
    
    # Send confirmation
    sio.emit('room_joined', {
        'room': room,
        'user_type': user_type,
        'message': f'Joined {room} room'
    }, room=sid)

@sio.event
def leave_room(sid, data):
    """Leave a specific room"""
    room = data.get('room', 'general')
    sio.leave_room(sid, room)
    
    if sid in connected_clients:
        connected_clients[sid]['room'] = None
    
    print(f"🚪 Client {sid} left room: {room}")
    
    sio.emit('room_left', {
        'room': room,
        'message': f'Left {room} room'
    }, room=sid)

@sio.event
def order_status_update(sid, data):
    """Handle order status updates from frontend"""
    order_id = data.get('order_id')
    new_status = data.get('status')
    user_type = data.get('user_type', 'admin')
    
    print(f"📋 Order {order_id} status update to {new_status} by {user_type}")
    
    # Broadcast to all connected clients
    sio.emit('order_updated', {
        'order_id': order_id,
        'status': new_status,
        'updated_by': user_type,
        'message': f'Order #{order_id} status changed to {new_status}'
    })

@sio.event
def new_order_created(sid, data):
    """Handle new order creation from frontend"""
    order_data = data.get('order')
    print(f"🆕 New order created: {order_data}")
    
    # Broadcast to admin and staff rooms
    sio.emit('new_order', {
        'order': order_data,
        'message': 'New order received!'
    }, room='admin')
    
    sio.emit('new_order', {
        'order': order_data,
        'message': 'New order received!'
    }, room='staff')

@sio.event
def order_tracking_request(sid, data):
    """Handle order tracking requests"""
    order_id = data.get('order_id')
    table_id = data.get('table_id')
    room_id = data.get('room_id')
    
    print(f"🔍 Order tracking request for order {order_id}")
    
    # Join specific tracking room
    tracking_room = f"tracking_{order_id}"
    sio.enter_room(sid, tracking_room)
    
    # Send confirmation
    sio.emit('tracking_started', {
        'order_id': order_id,
        'message': f'Started tracking Order #{order_id}'
    }, room=sid)

@sio.event
def waiter_call(sid, data):
    """Handle waiter call requests from customers"""
    try:
        table_number = data.get('table_number', 'Unknown')
        table_unique_id = data.get('table_unique_id', '')
        room_unique_id = data.get('room_unique_id', '')
        message = data.get('message', '')
        
        if not table_unique_id and not room_unique_id:
            print(f"❌ Waiter call error: Missing table_unique_id or room_unique_id")
            sio.emit('waiter_call_error', {
                'error': 'Table or room ID is required'
            }, room=sid)
            return
        
        call_id = f"call_{table_unique_id or room_unique_id}_{int(time.time())}"
        
        print(f"🔔 Waiter call from table {table_number} (ID: {call_id})")
        print(f"   Table Unique ID: {table_unique_id}")
        print(f"   Room Unique ID: {room_unique_id}")
        print(f"   Message: {message}")
        print(f"   Client SID: {sid}")
        
        # Emit to waiters room
        waiter_call_data = {
            'id': call_id,
            'table_number': table_number,
            'table_unique_id': table_unique_id,
            'room_unique_id': room_unique_id,
            'timestamp': time.time(),
            'status': 'pending',
            'customer_message': message
        }
        
        sio.emit('waiter_call', waiter_call_data, room='waiters')
        print(f"✅ Waiter call emitted to 'waiters' room")
        
        # Send confirmation to customer (to the specific client that made the call)
        confirmation_data = {
            'call_id': call_id,
            'message': 'Waiter call sent successfully',
            'table_number': table_number
        }
        sio.emit('waiter_call_sent', confirmation_data, room=sid)
        print(f"✅ Confirmation sent to client {sid}")
        
    except Exception as e:
        print(f"❌ Error handling waiter call: {e}")
        import traceback
        traceback.print_exc()
        sio.emit('waiter_call_error', {
            'error': str(e)
        }, room=sid)

@sio.event
def acknowledge_waiter_call(sid, data):
    """Handle waiter call acknowledgment"""
    call_id = data.get('call_id')
    
    print(f"✅ Waiter call {call_id} acknowledged")
    
    # Update call status
    sio.emit('waiter_call_update', {
        'id': call_id,
        'status': 'acknowledged',
        'timestamp': time.time()
    }, room='waiters')

@sio.event
def complete_waiter_call(sid, data):
    """Handle waiter call completion"""
    call_id = data.get('call_id')
    
    print(f"✅ Waiter call {call_id} completed")
    
    # Update call status
    sio.emit('waiter_call_update', {
        'id': call_id,
        'status': 'completed',
        'timestamp': time.time()
    }, room='waiters')

# Utility functions to emit events
def emit_order_update(order_id, new_status, user_type='admin'):
    """Emit order update event to all connected clients"""
    print(f"📤 Emitting order update: {order_id} -> {new_status}")
    sio.emit('order_updated', {
        'order_id': order_id,
        'status': new_status,
        'updated_by': user_type,
        'message': f'Order #{order_id} status changed to {new_status}'
    })

def emit_new_order(order_data):
    """Emit new order event to admin and staff"""
    print(f"📤 Emitting new order: {order_data.get('id', 'unknown')}")
    sio.emit('new_order', {
        'order': order_data,
        'message': 'New order received!'
    }, room='admin')
    
    sio.emit('new_order', {
        'order': order_data,
        'message': 'New order received!'
    }, room='staff')

def emit_order_status_to_tracking(order_id, order_data):
    """Emit order status to specific tracking room"""
    tracking_room = f"tracking_{order_id}"
    print(f"📤 Emitting order status to tracking room: {tracking_room}")
    sio.emit('order_status', {
        'order': order_data,
        'message': f'Status update for Order #{order_id}'
    }, room=tracking_room)

if __name__ == '__main__':
    print("🚀 Starting Socket.IO server on port 8001...")
    print("✅ Socket.IO server is ready!")
    print("🔌 Listening for connections...")
    print("📱 Frontend should connect to: http://localhost:8001")
    print("🌐 Django API is on: http://localhost:8000")
    print("🔗 HTTP endpoints available:")
    print("   - POST /emit_new_order")
    print("   - POST /emit_order_update")
    print("")
    print("Press Ctrl+C to stop the server")
    print("=" * 50)
    
    # Run the Socket.IO server
    # Bind to 0.0.0.0 to accept connections from all network interfaces
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', 8001)), app)
