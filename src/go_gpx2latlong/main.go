package main

import (
	"encoding/xml"
	"fmt"
	"io/ioutil"
//	"os"
	"path/filepath"
)

type TrackPoint struct {
	Lat string `xml:"lat,attr"`
	Lon string `xml:"lon,attr"`
}

func main() {
	// Directory containing GPX files
	dir := "/export_55533644/activities"

	// Create a map to store unique lat/lon combinations
	uniquePoints := make(map[string]struct{})

	// Read files in the directory
	files, err := ioutil.ReadDir(dir)
	if err != nil {
		fmt.Println("Error reading directory:", err)
		return
	}

	// Process each GPX file
	for _, file := range files {
		if filepath.Ext(file.Name()) == ".gpx" {
			filePath := filepath.Join(dir, file.Name())
			if err := processGPXFile(filePath, uniquePoints); err != nil {
				fmt.Printf("Error processing file %s: %v\n", filePath, err)
			}
		}
	}

	// Print unique lat/lon combinations
	//fmt.Println("Unique lat/lon combinations:")
	for point := range uniquePoints {
		fmt.Println(point)
	}
}

// Process a single GPX file
func processGPXFile(filePath string, uniquePoints map[string]struct{}) error {
	// Read GPX file
	xmlData, err := ioutil.ReadFile(filePath)
	if err != nil {
		return fmt.Errorf("error reading GPX file: %v", err)
	}

	// Parse XML data into TrackPoints
	var gpx struct {
		Track []struct {
			TrackSeg []struct {
				TrackPoints []TrackPoint `xml:"trkpt"`
			} `xml:"trkseg"`
		} `xml:"trk"`
	}
	if err := xml.Unmarshal(xmlData, &gpx); err != nil {
		return fmt.Errorf("error parsing GPX: %v", err)
	}

	// Extract unique lat/lon combinations
	for _, track := range gpx.Track {
		for _, seg := range track.TrackSeg {
			for _, point := range seg.TrackPoints {
				point.Lat = point.Lat+"000000"
				point.Lon = point.Lon+"000000"
				point.Lat = point.Lat[:6]
				point.Lon = point.Lon[:7]
				uniquePoints[point.Lat+"5,"+point.Lon+"5,0"] = struct{}{}
			}
		}
	}

	return nil
}
