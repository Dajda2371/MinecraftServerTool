import sys
import api.db
import getpass

def main():
    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        password = getpass.getpass("Enter new password for 'admin': ")
    
    if api.db.set_user_password("admin", password):
        print("Password for 'admin' updated successfully.")
    else:
        print("User 'admin' does not exist. Please run the application once to initialize the database.")

if __name__ == "__main__":
    main()
