package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

var db *pgxpool.Pool

func main() {
	dsn := os.Getenv("PG_DSN")
	if dsn == "" {
		dsn = "postgres://vibe:vibe@postgres:5432/vibe"
	}
	ctx := context.Background()
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		log.Printf("ERROR prescription-svc: %v", err)
		os.Exit(1)
	}
	cfg.ConnConfig.ConnectTimeout = 2 * time.Second
	db, err = pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		log.Printf("ERROR prescription-svc: %v", err)
		os.Exit(1)
	}
	if err := initDB(ctx); err != nil {
		log.Printf("ERROR prescription-svc: %v", err)
	}

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())

	r.GET("/healthz", healthz)
	r.POST("/prescriptions", createPrescription)
	r.GET("/prescriptions/:patient_id/active", getActive)
	r.GET("/prescriptions/id/:id", getByID)

	log.Println("prescription-svc listening on 8080")
	r.Run("0.0.0.0:8080")
}

func initDB(ctx context.Context) error {
	_, err := db.Exec(ctx, `CREATE TABLE IF NOT EXISTS prescriptions(
		id serial PRIMARY KEY,
		patient_id text,
		doctor_id text,
		medication text,
		dosage text,
		duration_days int,
		issued_at timestamptz DEFAULT now(),
		active bool DEFAULT true
	)`)
	return err
}

func healthz(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok", "service": "prescription-svc"})
}

func createPrescription(c *gin.Context) {
	var body struct {
		PatientID   string `json:"patient_id"`
		DoctorID    string `json:"doctor_id"`
		Medication  string `json:"medication"`
		Dosage      string `json:"dosage"`
		DurationDays int   `json:"duration_days"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "bad request"})
		return
	}
	var id int
	err := db.QueryRow(context.Background(),
		"INSERT INTO prescriptions(patient_id,doctor_id,medication,dosage,duration_days) VALUES($1,$2,$3,$4,$5) RETURNING id",
		body.PatientID, body.DoctorID, body.Medication, body.Dosage, body.DurationDays,
	).Scan(&id)
	if err != nil {
		log.Printf("ERROR prescription-svc: %v", err)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "db error"})
		return
	}
	c.JSON(http.StatusCreated, gin.H{"id": id, "patient_id": body.PatientID, "medication": body.Medication, "active": true})
}

func getActive(c *gin.Context) {
	patientID := c.Param("patient_id")
	rows, err := db.Query(context.Background(),
		"SELECT id,patient_id,doctor_id,medication,dosage,duration_days,issued_at,active FROM prescriptions WHERE patient_id=$1 AND active=true",
		patientID)
	if err != nil {
		log.Printf("ERROR prescription-svc: %v", err)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "db error"})
		return
	}
	defer rows.Close()
	result := []map[string]interface{}{}
	for rows.Next() {
		var id, duration int
		var pid, did, med, dos string
		var issued time.Time
		var active bool
		if err := rows.Scan(&id, &pid, &did, &med, &dos, &duration, &issued, &active); err != nil {
			continue
		}
		result = append(result, map[string]interface{}{
			"id": id, "patient_id": pid, "doctor_id": did, "medication": med,
			"dosage": dos, "duration_days": duration, "issued_at": issued, "active": active,
		})
	}
	c.JSON(http.StatusOK, result)
}

func getByID(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	var pid, did, med, dos string
	var duration int
	var issued time.Time
	var active bool
	err := db.QueryRow(context.Background(),
		"SELECT patient_id,doctor_id,medication,dosage,duration_days,issued_at,active FROM prescriptions WHERE id=$1",
		id,
	).Scan(&pid, &did, &med, &dos, &duration, &issued, &active)
	if err != nil {
		if err.Error() == "no rows in result set" {
			c.JSON(http.StatusNotFound, gin.H{"error": "not found"})
			return
		}
		log.Printf("ERROR prescription-svc: %v", err)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "db error"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"id": id, "patient_id": pid, "doctor_id": did, "medication": med, "dosage": dos, "duration_days": duration, "issued_at": issued, "active": active})
}
