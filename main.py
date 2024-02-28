import importCSV
import DataAudit

if __name__ == "__main__":
    print("Welcome to Cardre!\nSelect module to run:\n\n1: CSV Importer\n2: Data Audit\n3: Fine Classing\n\n")
    while True:
        module = input("Enter module number ('quit' to exit, 'help' to list modules): ")
        if module == "help":
            print("Available modules:\n 1: CSV Importer\n2: Data Audit\n\n")
            continue
        if module == "1":
            df = importCSV.load_csv()
            continue
        
        elif module == "2":
            try:
                df
            except NameError:
                print("No DataFrame loaded. Please load a DataFrame first.\n")
                df = importCSV.load_csv()
            else:
                DataAudit.audit(df)
            continue   
        
        elif module == "quit":
            print("Quitting Cardre...")
            break  # Return to the main menu
        else:
            print("Invalid module number. Please try again.")
    
    # Code to execute when the script is run directly
    pass