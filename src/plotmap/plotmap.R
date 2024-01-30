# install.packages("ggplot2")
# install.packages("maps")
# install.packages("ggmap")
# install.packages("dplyr")
# install.packages("sp")

library(ggplot2)
library(maps)
library(ggmap)
library(dplyr)
library(sp)
library(osmdata)


# Get Connecticut map data
ct_map <- map_data("state", region = "connecticut")
ct_counties <- map_data("county", region = "connecticut")

ct_boundary <- getbb("Connecticut") %>% opq() %>% add_osm_feature(key = "boundary", value = "administrative")# %>% osmdata_sf()


file_path <- "distance_3.csv"
delta = 0.0005


my_data <- read.csv(file_path)  %>% select(long, lat, Dist) %>% filter(Dist < 3.5)
my_data$colorx <- ifelse(my_data$Dist < 0.0, "under 0.0"
                , ifelse(my_data$Dist < 0.91, "under 1.0"
                , ifelse(my_data$Dist < 1.01, "zboundary"
                , ifelse(my_data$Dist < 1.41, "under 1.5"
                , ifelse(my_data$Dist < 1.51, "zboundary"
                , ifelse(my_data$Dist < 1.91, "under 2.0"
                , ifelse(my_data$Dist < 1.92, "under 2.0"
                , "under 1.0")))))))

ct_boundary_coordinates <- ct_map %>% select(long, lat)

ct_polygon <- SpatialPolygons(list(Polygons(list(Polygon(ct_boundary_coordinates)), ID = "CT")))

is_inside <- (point.in.polygon(my_data$long, my_data$lat, ct_map$long, ct_map$lat) != 0)

my_ct_data <- filter(my_data, is_inside)

my_plot <- ggplot() +
  geom_polygon(data = ct_map, aes(x = long, y = lat, group = group), fill = "white", color = "black") +
  geom_rect(data = my_ct_data, aes(xmin = long-delta, xmax = long+delta, ymin = lat-delta, ymax = lat+delta, fill = colorx)) +
  geom_polygon(data = ct_counties, aes(x = long, y = lat, group = group), fill=NA, color = "black") +
  geom_sf(data = ct_boundary$osm_lines, inherit.aes = TRUE, fill=NA, color = "black", size = 0.1) +
  scale_size_continuous(range = c(3, 5)) + # Adjust the size range as needed
  coord_fixed(ratio = 1.4) + # Ensure aspect ratio is correct
  theme_minimal() +
  labs(title = "Andy Walks Connecticut")

# Save the ggplot as a PNG file
ggsave("AndyWalksConnecticut.png", my_plot, width = 15, height = 15)

