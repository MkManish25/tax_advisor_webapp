#!/usr/bin/env python3
"""
Database setup script for Tax Advisor Application
Creates the UserFinancials table in Supabase
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_user_financials_table():
    """Create the UserFinancials table if it doesn't exist"""
    
    # SQL for creating the UserFinancials table
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS UserFinancials (
        session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        gross_salary NUMERIC(15, 2) NOT NULL,
        basic_salary NUMERIC(15, 2) NOT NULL,
        hra_received NUMERIC(15, 2) DEFAULT 0,
        rent_paid NUMERIC(15, 2) DEFAULT 0,
        deduction_80c NUMERIC(15, 2) DEFAULT 0,
        deduction_80d NUMERIC(15, 2) DEFAULT 0,
        standard_deduction NUMERIC(15, 2) DEFAULT 50000,
        professional_tax NUMERIC(15, 2) DEFAULT 0,
        tds NUMERIC(15, 2) DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """
    
    try:
        # Get database URL from environment
        db_url = os.getenv('DB_URL')
        if not db_url:
            logger.error("DB_URL environment variable not found")
            logger.error("Please set DB_URL in your .env file")
            return False
        
        # Connect to database
        logger.info("Connecting to database...")
        connection = psycopg2.connect(db_url)
        cursor = connection.cursor()
        
        # Create table
        logger.info("Creating UserFinancials table...")
        cursor.execute(create_table_sql)
        
        # Commit the transaction
        connection.commit()
        
        # Verify table creation
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'userfinancials'
            );
        """)
        
        table_exists = cursor.fetchone()[0]
        
        if table_exists:
            logger.info("✅ UserFinancials table created successfully!")
            
            # Show table structure
            cursor.execute("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns 
                WHERE table_name = 'userfinancials'
                ORDER BY ordinal_position;
            """)
            
            columns = cursor.fetchall()
            logger.info("Table structure:")
            for column in columns:
                logger.info(f"  - {column[0]}: {column[1]} {'(NULL)' if column[2] == 'YES' else '(NOT NULL)'} {f'DEFAULT: {column[3]}' if column[3] else ''}")
            
        else:
            logger.error("❌ Table creation failed")
            return False
        
        cursor.close()
        connection.close()
        
        return True
        
    except psycopg2.Error as e:
        logger.error(f"❌ Database error: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return False

def test_table_access():
    """Test if we can access the created table"""
    try:
        db_url = os.getenv('DB_URL')
        connection = psycopg2.connect(db_url)
        cursor = connection.cursor()
        
        # Try to insert a test record
        cursor.execute("""
            INSERT INTO UserFinancials (gross_salary, basic_salary)
            VALUES (500000, 300000)
            RETURNING session_id;
        """)
        
        session_id = cursor.fetchone()[0]
        logger.info(f"✅ Test record inserted with session_id: {session_id}")
        
        # Clean up test record
        cursor.execute("DELETE FROM UserFinancials WHERE session_id = %s", (session_id,))
        logger.info("✅ Test record cleaned up")
        
        connection.commit()
        cursor.close()
        connection.close()
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Table access test failed: {e}")
        return False

def main():
    """Main function to run the database setup"""
    logger.info("🚀 Starting database setup for Tax Advisor Application")
    logger.info("=" * 50)
    
    # Check if DB_URL is set
    if not os.getenv('DB_URL'):
        logger.error("❌ DB_URL environment variable not found")
        logger.error("Please create a .env file with your database connection string")
        logger.error("Example: DB_URL=postgresql://postgres:password@host:5432/postgres")
        sys.exit(1)
    
    # Create table
    if create_user_financials_table():
        logger.info("=" * 50)
        
        # Test table access
        logger.info("Testing table access...")
        if test_table_access():
            logger.info("✅ Database setup completed successfully!")
            logger.info("You can now run the application with: python app.py")
        else:
            logger.error("❌ Table access test failed")
            sys.exit(1)
    else:
        logger.error("❌ Database setup failed")
        sys.exit(1)

if __name__ == "__main__":
    main() 