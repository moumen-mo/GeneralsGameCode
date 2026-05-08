import os
import json


def list_files_in_folder(folder_path, ignore_folders=None, only_folders=None):
    """
    List all files and folders in a directory.
    
    Args:
        folder_path (str): Root folder path to scan
        ignore_folders (list): List of subfolder names to exclude (e.g., ['node_modules', '.git'])
        only_folders (list): List of subfolder names to include. If set, only these folders are scanned
    
    Returns:
        list: All files and folders found
    """
    file_list = []
    ignore_folders = ignore_folders or []
    only_folders = only_folders or []

    for root, dirs, files in os.walk(folder_path):
        # Filter directories based on ignore/only lists
        dirs_to_remove = []
        for dir_name in dirs:
            # Check if folder should be ignored
            if ignore_folders and dir_name in ignore_folders:
                dirs_to_remove.append(dir_name)
            # Check if only specific folders should be processed
            elif only_folders and dir_name not in only_folders:
                dirs_to_remove.append(dir_name)
        
        # Remove ignored directories from dirs list to prevent os.walk from traversing them
        for dir_name in dirs_to_remove:
            dirs.remove(dir_name)
        
        file_list.append(os.path.join(root))

        for file_name in files:
            file_full_path = os.path.join(root, file_name)
            file_list.append(file_full_path)

    return file_list

# Example usage:
folder_path = 'E:\\PythonProjects\\General_Zero_Hour\\GeneralsGameCode\\build\\win32'

# Option 1: Get all files (default behavior)
# file_paths = list_files_in_folder(folder_path)

# Option 2: Ignore specific subfolders
# file_paths = list_files_in_folder(folder_path, ignore_folders=['Debug', 'Release', '.git'])

# Option 3: Scout only specific subfolders
file_paths = list_files_in_folder(folder_path, only_folders=['Release', 'Generals', 'GeneralsMD'])

# Separate directories and files
directories = [p for p in file_paths if os.path.isdir(p)]
files = [p for p in file_paths if os.path.isfile(p)]

output_data = {
    'summary': {
        'total_items': len(file_paths),
        'directories': len(directories),
        'files': len(files),
        'root_path': folder_path
    },
    'directories': sorted(directories),
    'files': sorted(files)
}

# Write formatted JSON
with open('output.json', 'w') as f:
    json.dump(output_data, f, indent=2)

# Print summary to console
print(f"\n{'='*60}")
print(f"File Listing Summary")
print(f"{'='*60}")
print(f"Root Path: {folder_path}")
print(f"Total Items: {len(file_paths)}")
print(f"  - Directories: {len(directories)}")
print(f"  - Files: {len(files)}")
print(f"{'='*60}")
print(f"Output saved to: output.json\n")
