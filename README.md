# 🍽️ Digital QR Food Ordering System

A modern, full-stack food ordering system with QR code-based table management, real-time order tracking, and comprehensive billing system.

## 🏗️ Architecture

- **Backend**: Django REST API with PostgreSQL in production
- **Frontend**: React with TypeScript and Material-UI
- **Database**: SQLite for local development, PostgreSQL for production

## ✨ Features

### 🍕 Customer Features
- **QR Code Ordering**: Scan QR codes to access restaurant menu
- **Anonymous Ordering**: Order without creating an account
- **Real-time Order Tracking**: Track order status in real-time
- **Modern UI/UX**: Beautiful, responsive interface
- **Cart Management**: Add/remove items with persistent cart
- **Bill Portal**: View and print detailed bills
- **Multiple Orders**: Place multiple orders from same table

### 🏢 Restaurant Management
- **Table Management**: Visual table arrangement with drag & drop
- **Floor Management**: Organize tables by floors
- **Room Management**: Hotel room ordering system
- **Order Management**: Real-time order status updates
- **Menu Management**: Add/edit menu items with images
- **Staff Management**: Complete HR system with attendance tracking
- **Analytics Dashboard**: Revenue, orders, and performance metrics

### 🏨 Hotel Features
- **Room QR Codes**: Unique QR codes for each hotel room
- **Room Status**: Track room availability and occupancy
- **In-room Ordering**: Guests can order food to their rooms

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Node.js 16+
- npm or yarn

### Installation

1. **Clone the repository**
```bash
git clone <repository-url>
cd digitalqr
```

2. **Install Python dependencies**
```bash
pip install django djangorestframework django-cors-headers pillow qrcode
```

3. **Install Node.js dependencies**
```bash
cd frontend
npm install
cd ..
```

4. **Run database migrations**
```bash
python manage.py migrate
```

5. **Create superuser (optional)**
```bash
python manage.py createsuperuser
```

## 🌐 Running the Application

### Method 1: Quick Start Script
```bash
./start.sh
```

This will:
- Start Django backend on port 8000
- Start React frontend on port 3000
- Display access URLs

### Method 2: Manual Start

**Backend (Django)**
```bash
python manage.py runserver 8000
```

**Frontend (React)**
```bash
cd frontend
npm start
```

## 📁 Project Structure

```
digitalqr/
├── cafe/                 # Django app (models, views, API)
├── pr1/                  # Django project settings
├── frontend/             # React frontend
│   ├── src/
│   │   ├── components/   # React components
│   │   ├── services/     # API services
│   │   ├── context/      # React context
│   │   └── types/        # TypeScript types
│   └── public/           # Static assets
├── media/                # Uploaded files (QR codes, images)
├── db.sqlite3           # SQLite database
├── manage.py            # Django management script
└── start.sh             # Startup script
```

## 🔧 API Endpoints

The Django backend provides REST API endpoints for:
- Authentication (`/api/auth/`)
- Menu management (`/api/menu/`)
- Table management (`/api/tables/`)
- Order management (`/api/orders/`)
- Staff management (`/api/staff/`)
- Billing (`/api/bills/`)
- Dashboard analytics (`/api/dashboard/`)

## 🎯 Key Components

### Backend (Django)
- **Models**: User, MenuItem, Table, Order, Bill, Staff, etc.
- **API Views**: RESTful endpoints for all operations
- **Authentication**: Custom user model with phone-based auth
- **File Management**: QR code generation and image uploads

### Frontend (React)
- **Components**: Modular React components for each feature
- **State Management**: React Context for authentication
- **UI Framework**: Material-UI for consistent design
- **Routing**: React Router for navigation
- **API Integration**: Axios for backend communication

## 🛠️ Development

### Adding New Features
1. Create Django models in `cafe/models.py`
2. Add API views in `cafe/api_views.py`
3. Create React components in `frontend/src/components/`
4. Update TypeScript types in `frontend/src/types/`

### Database Changes
```bash
python manage.py makemigrations
python manage.py migrate
```

### Frontend Development
```bash
cd frontend
npm start
```

## 📱 Access URLs

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000/api/
- **Django Admin**: http://localhost:8000/admin/

## 🔒 Security Features

- CSRF protection
- CORS configuration for frontend
- Authentication middleware
- Permission-based access control
- Secure file uploads

## 📊 Database

The system uses SQLite only for local development. Production deployments should use PostgreSQL via the DATABASE_URL environment variable.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License.



