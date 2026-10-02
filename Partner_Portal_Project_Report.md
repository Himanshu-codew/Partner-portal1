# Project Report: Partner Portal
**B2B Affiliate & Lead Management System**

---

## 1. Project Overview & Objective
The **Partner Portal** is a comprehensive Business-to-Business (B2B) web application designed to bridge the gap between the core business (Admin) and its affiliated partners. 

**Main Objective:** To provide a centralized platform where partners can submit potential client leads, track their conversion progress, and monitor their earned commissions, while allowing the Admin to seamlessly manage orders, distribute content, and handle support queries.

---

## 2. Technology Stack
*   **Backend Framework:** Python / Django (Robust, secure, and scalable)
*   **Frontend Design:** HTML5, CSS3, Bootstrap 5 (Responsive UI/UX)
*   **JavaScript Libraries:** Chart.js (For dynamic dashboard analytics)
*   **Database:** SQLite (Development) / PostgreSQL (Production ready)
*   **Version Control:** Git & GitHub
*   **Deployment:** Render.com (Cloud Hosting platform)

---

## 3. Working Flow (How it works)

The system is divided into two distinct roles, each with its own secured environment and workflow.

### A. The Partner Flow
1. **Onboarding:** Partner registers an account and waits for Admin approval.
2. **Lead Submission:** Partner submits client details (Leads) through the portal.
3. **Tracking:** Partner tracks the status of the lead (New -> Contacted -> Converted).
4. **Earnings:** Once a lead converts into an Order, the partner sees their calculated commission in the "Commissions" tab.
5. **Support & Updates:** Partner can read company announcements, download resources, and raise support tickets if they need help.

### B. The Admin Flow
1. **Partner Management:** Admin approves or rejects new partner registrations.
2. **Lead Processing:** Admin updates lead statuses as the sales team interacts with the client.
3. **Order & Revenue Management:** Admin creates Orders from converted leads, sets the total client amount, and calculates the partner's commission.
4. **Financial Oversight:** Admin views the **Net Profit** (Total Client Amount - Total Partner Commission).
5. **Content Distribution:** Admin uploads Documents and Announcements (can be Public for all, or Private for specific partners).
6. **Customer Support:** Admin replies to partner tickets and updates issue statuses.

---

## 4. Key Modules & Features Developed

### 🔐 Authentication & Authorization (RBAC)
*   Custom role-based access control ensuring Partners only see their own data, while Admins have a global view.
*   Profile approval system ensuring only verified partners can access the dashboard.

### 📊 Interactive Dashboards
*   Real-time analytical cards showing Total Leads, Orders, and Earnings.
*   Visual Doughnut and Bar charts powered by **Chart.js** to track lead conversion ratios.

### 💰 Financial Engine & Commission Logic
*   Advanced database querying using Django ORM (`Sum`, `ExpressionWrapper`, `F` objects) to dynamically calculate profits without slowing down the system.
*   Clickable filtering system to instantly sort orders by "Paid" or "Pending" commissions.

### 📢 Targeted Content Delivery
*   A complex Many-to-Many relationship system allowing the Admin to push specific policy updates or training materials to *selected* partners only.

### 🎧 Support Ticketing System
*   A fully functional Helpdesk where partners can raise issues. 
*   Dual-view system: Admins get a split-screen view to read queries and type replies, while Partners get a read-only view of the Admin's response.

---

## 5. Development & Deployment Journey

*   **Learning & Research:** The logic for revenue splitting and targeted permissions required deep-diving into Django's advanced ORM capabilities and template context processors.
*   **Version Control:** Regular commits were pushed to **GitHub**, ensuring code backup and version tracking.
*   **Deployment:** The project is live and deployed on **Render.com**. Render was chosen for its seamless GitHub integration and automatic build deployments for Python web apps.

---

## 6. Future Scope
*   **Email Notifications:** Integrating SMTP to automatically email partners when their commission is paid or a ticket is replied to.
*   **Export to Excel/PDF:** Allowing admins to download monthly financial reports.
*   **Payment Gateway Integration:** Automating the actual payout process directly through the portal.
